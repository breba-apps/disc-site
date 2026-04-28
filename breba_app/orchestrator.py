import asyncio
import logging
import mimetypes
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from baml_py import BamlStream

from breba_app.chainlit_bridge import to_baml_message as _message_to_baml
from breba_app.llm_utils import BrebaMessage
from breba_app.coder_agent.agent import stream_user_response_or_coder, run_coder_agent, \
    update_executive_summary, AGENTS_MD_FILE
from breba_app.coder_agent.baml_client.async_client import b
from breba_app.coder_agent.baml_client.stream_types import Coder as CoderStream, ResponseToUser as ResponseToUserStream
from breba_app.coder_agent.baml_client.types import LLMMessage, Coder, ResponseToUser
from breba_app.config import INDEX_FILE_NAME
from breba_app.events import event_bus
from breba_app.events.before_handoff_to_coder import BeforeHandoffToCoder
from breba_app.events.bus import Consumer, HandleContext
from breba_app.events.coder_completed import CoderCompleted
from breba_app.filesystem import InMemoryFileStore
from breba_app.status_service import agent_task, update_status
from breba_app.storage import read_all_files_in_memory
from breba_app.template_agent.agent import TemplateAgent
from breba_app.template_agent.baml_client.types import WebsiteSpecification
from breba_app.tools.upload_files import upload_file

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorState:
    messages: list[BrebaMessage]
    filestore: InMemoryFileStore


# Keyed by (user_name, product_id)
_state_store: dict[tuple[str, str], OrchestratorState] = defaultdict(
    lambda: OrchestratorState(messages=[], filestore=InMemoryFileStore())
)


_AGENTS_MD_MARKER = "[AGENTS.md]"


def _inject_agents_md(messages: list[BrebaMessage], content: str) -> None:
    """Remove any previous AGENTS.md injection and append the updated one at the end.

    Searches from the end since the injection is typically near the tail of a long message list.
    """
    marker_idx = next(
        (i for i in range(len(messages) - 1, -1, -1)
         if messages[i].role == "user" and messages[i].content.startswith(_AGENTS_MD_MARKER)),
        None
    )
    if marker_idx is not None:
        # Remove the marker message and the immediately following assistant ack (if present)
        del messages[marker_idx]
        if marker_idx < len(messages) and messages[marker_idx].role == "assistant":
            del messages[marker_idx]
    messages.append(BrebaMessage(
        role="user",
        content=f"{_AGENTS_MD_MARKER}\nHere are the project notes capturing user preferences, decisions, and constraints:\n{content}"
    ))
    messages.append(BrebaMessage(
        role="assistant",
        content="I understand the project context and will keep these preferences in mind."
    ))


class ExecutiveSummaryGenerationConsumer(Consumer):
    def __init__(self):
        self.id = "executive_summary_generator_consumer"
        super().__init__()

    async def handle(self, ctx: HandleContext, event: BeforeHandoffToCoder) -> None:
        logger.info("Generating executive summary...")
        new_content = await update_executive_summary(messages=event.messages, filestore=event.filestore)
        if new_content:
            orchestrator_state = load_state(event.user_name, event.product_id)
            _inject_agents_md(orchestrator_state.messages, new_content)


class AgentsMdContextConsumer(Consumer):
    def __init__(self):
        self.id = "agents_md_context_consumer"
        super().__init__()

    async def handle(self, ctx: HandleContext, event: CoderCompleted) -> None:
        if event.filestore.file_exists(AGENTS_MD_FILE):
            orchestrator_state = load_state(event.user_name, event.product_id)
            _inject_agents_md(orchestrator_state.messages, event.filestore.read_text(AGENTS_MD_FILE))


async def init_orchestrator(user_name: str, product_id: str) -> OrchestratorState:
    filestore, _, _ = await asyncio.gather(
        read_all_files_in_memory(user_name, product_id),
        event_bus.subscribe(BeforeHandoffToCoder, ExecutiveSummaryGenerationConsumer()),
        event_bus.subscribe(CoderCompleted, AgentsMdContextConsumer()),
    )
    state = OrchestratorState(messages=[], filestore=filestore)
    # Inject AGENTS.md at the start of context for returning users so all agents have project notes immediately
    if filestore.file_exists(AGENTS_MD_FILE):
        _inject_agents_md(state.messages, filestore.read_text(AGENTS_MD_FILE))
    save_state(user_name, product_id, state)
    return state


def state_exists(user_name: str, product_id: str) -> bool:
    """Return True if an active session exists for this user/product pair."""
    return (user_name, product_id) in _state_store


def load_state(user_name: str, product_id: str) -> OrchestratorState:
    """Retrieve the current state for a given user/product pair."""
    # TODO: make deep copy of state before passing it out
    return _state_store[(user_name, product_id)]


def save_state(user_name: str, product_id: str, state: OrchestratorState) -> None:
    """Persist the given state for a user/product pair."""
    _state_store[(user_name, product_id)] = state


def _to_baml_messages(messages: list[BrebaMessage]) -> list[LLMMessage]:
    return [_message_to_baml(m) for m in messages]


async def baml_stream_and_collect_user_response(stream: BamlStream, stream_receiver) -> str:
    async def gen() -> AsyncIterator[str]:
        async for msg in stream:
            if type(msg) is CoderStream:
                update_status("Coder is writing the code...")
                # ignore coder messages because we don't want to stream them
                continue
            if type(msg) is ResponseToUserStream:
                # Stream message to user and collect the final message, then store the message into message history
                if not msg.response_to_user:
                    continue
                yield msg.response_to_user

    await stream_receiver(gen())

    return await stream.get_final_response()


@agent_task
async def edit_product(user_name: str, product_id: str, message: BrebaMessage,
                       coder_completed_callback,
                       stream_to_user_callback):
    # TODO: This duplication can be overcome by memoization, or passing state as param
    orchestrator_state = load_state(user_name, product_id)
    file_store = orchestrator_state.filestore
    update_status("Thinking...")
    orchestrator_state.messages.append(message)
    response = await stream_user_response_or_coder(messages=_to_baml_messages(orchestrator_state.messages),
                                                   filestore=file_store)

    final_response = await baml_stream_and_collect_user_response(response, stream_to_user_callback)
    if isinstance(final_response, Coder):
        await event_bus.emit(
            BeforeHandoffToCoder(user_name=user_name, product_id=product_id,
                                 messages=_to_baml_messages(orchestrator_state.messages),
                                 filestore=file_store))
        coder_response = await run_coder_agent(messages=_to_baml_messages(orchestrator_state.messages),
                                               filestore=file_store)
        orchestrator_state.messages.append(BrebaMessage(role="assistant", content=coder_response.content))
        await coder_completed_callback(user_name, product_id, file_store)
        update_status("The website is ready to be deployed. Use the 🚀 from the sidebar to deploy your website")
    elif isinstance(final_response, ResponseToUser):
        orchestrator_state.messages.append(BrebaMessage(role="assistant", content=final_response.response_to_user))
    else:
        raise ValueError("Unexpected response type")


@agent_task
async def start_product(user_name: str, product_id: str, message: BrebaMessage,
                        coder_completed_callback, message_to_user_callback):
    t_agent = TemplateAgent(user_name, product_id)
    response = await t_agent.build_specification(message, message_to_user_callback)

    # We will only proceed to next step, if we have a website specification. Otherwise, wait for additional user input
    if isinstance(response, WebsiteSpecification):
        # TODO: This duplication can be overcome by memoization, or passing state as param, or using a class
        orchestrator_state = load_state(user_name, product_id)
        file_store = orchestrator_state.filestore
        new_spec = response.spec

        orchestrator_state.messages.append(message)
        orchestrator_state.messages.append(BrebaMessage(role="assistant", content=new_spec))
        orchestrator_state.messages.append(
            BrebaMessage(role="user", content="Let's use this specification to build the website"))
        # TODO: Need to emit without waiting, but that requires proper synchronization of filestore with persistent storage
        #  Otherwise the AGENTS.md will not be saved if coder finishes first.
        # Emit before coder so AGENTS.md is written to filestore and persisted alongside the product files.
        # Reuses the same BeforeHandoffToCoder consumer as edit_product.
        await event_bus.emit(
            BeforeHandoffToCoder(user_name=user_name, product_id=product_id,
                                 messages=_to_baml_messages(orchestrator_state.messages),
                                 filestore=file_store))
        update_status("Coder is writing the code...")
        coder_response = await run_coder_agent(messages=_to_baml_messages(orchestrator_state.messages),
                                               filestore=file_store)
        orchestrator_state.messages.append(BrebaMessage(role="assistant", content=coder_response.content))
        await coder_completed_callback(user_name, product_id, file_store)

        update_status("The website is ready to be deployed. Use the 🚀 from the sidebar to deploy your website")


async def handle_user_message(user_name: str, product_id: str, message: BrebaMessage,
                              coder_completed_callback, stream_to_user_callback):
    orchestrator_state = load_state(user_name, product_id)
    file_store = orchestrator_state.filestore
    if file_store.file_exists(INDEX_FILE_NAME):
        await edit_product(user_name, product_id, message, coder_completed_callback, stream_to_user_callback)
    else:
        await start_product(user_name, product_id, message, coder_completed_callback, stream_to_user_callback)


_PROJECT_ROOT_FILES = {"favicon.ico"}


@agent_task
async def handle_file_upload(user_name: str, product_id: str, message: BrebaMessage,
                             coder_completed_callback, stream_to_user_callback):
    project_root_elements = []
    image_elements = []
    non_image_elements = []
    for el in message.elements:
        if el.name in _PROJECT_ROOT_FILES:
            project_root_elements.append(el)
        else:
            content_type, _ = mimetypes.guess_type(el.name)
            if content_type and content_type.startswith("image/"):
                image_elements.append(el)
            else:
                non_image_elements.append(el)

    try:
        uploaded_paths = []
        project_root_paths = []

        if project_root_elements:
            orchestrator_state = load_state(user_name, product_id)
            for el in project_root_elements:
                orchestrator_state.filestore.write_bytes(el.name, Path(el.path).read_bytes())
                project_root_paths.append(el.name)

        if non_image_elements:
            non_image_paths = await asyncio.gather(*(
                upload_file(user_name=user_name, product_id=product_id, file_path=Path(el.path),
                            file_name=el.name, description=message.content) for el in non_image_elements))
            uploaded_paths.extend(non_image_paths)

        if image_elements:
            orchestrator_state = load_state(user_name, product_id)
            messages_for_intent = _to_baml_messages(orchestrator_state.messages) + [_message_to_baml(message)]
            upload_intent = await b.ShouldUploadToAssets(messages_for_intent)

            if upload_intent.problem:
                await stream_to_user_callback(upload_intent.problem)
                return

            if upload_intent.upload:
                image_paths = await asyncio.gather(*(
                    upload_file(user_name=user_name, product_id=product_id, file_path=Path(el.path),
                                file_name=el.name, description=message.content) for el in image_elements))
                uploaded_paths.extend(image_paths)

        if project_root_paths or uploaded_paths or image_elements:
            content_parts = []
            if project_root_paths:
                content_parts.append("Here are project files added to the website root:\n"
                                     + "\n".join(f"- {p}" for p in project_root_paths))
            if uploaded_paths:
                content_parts.append("Here are newly uploaded files:\n"
                                     + "\n".join(f"- {p}" for p in uploaded_paths))
            # Strip project-root files from elements — they're already in the filestore
            # and their MIME type (e.g. image/vnd.microsoft.icon) would be rejected by the LLM.
            forwarded_elements = [el for el in message.elements if el.name not in _PROJECT_ROOT_FILES]
            if content_parts:
                updated_content = "\n\n".join(content_parts) + "\n\n" + message.content
                message = BrebaMessage(role="user", content=updated_content, elements=forwarded_elements)
            else:
                message = BrebaMessage(role="user", content=message.content, elements=forwarded_elements)

            await handle_user_message(user_name, product_id, message,
                                      coder_completed_callback=coder_completed_callback,
                                      stream_to_user_callback=stream_to_user_callback)
        else:
            update_status("Something went wrong uploading files. Please try again, or contact support.")
    except ValueError as e:
        update_status(str(e))
    except Exception as e:
        logging.exception("Error uploading files")
        update_status("Something went wrong while uploading the file. Try again later, or contact support.")
