import asyncio
import logging
import mimetypes
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import base64

from baml_py import BamlStream, Image

from breba_app.coder_agent.agent import stream_user_response_or_coder, run_coder_agent, generate_executive_summary
from breba_app.coder_agent.baml_client.async_client import b
from breba_app.coder_agent.baml_client.stream_types import Coder as CoderStream, ResponseToUser as ResponseToUserStream
from breba_app.coder_agent.baml_client.types import LLMMessage, Coder, ResponseToUser
from breba_app.config import INDEX_FILE_NAME
from breba_app.controllers.product_controller import set_product_executive_summary
from breba_app.events import event_bus
from breba_app.events.before_handoff_to_coder import BeforeHandoffToCoder
from breba_app.events.bus import Consumer, HandleContext
from breba_app.filesystem import InMemoryFileStore
from breba_app.models.product import Product
from breba_app.status_service import agent_task, update_status
from breba_app.storage import read_all_files_in_memory
from breba_app.template_agent.agent import TemplateAgent
from breba_app.template_agent.baml_client.types import WebsiteSpecification
from breba_app.tools.upload_files import upload_file

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorState:
    messages: list[LLMMessage]
    executive_summary: str
    filestore: InMemoryFileStore


# Keyed by (user_name, product_id)
_state_store: dict[tuple[str, str], OrchestratorState] = defaultdict(
    lambda: OrchestratorState(
        messages=[],
        executive_summary="",
        filestore=InMemoryFileStore()
    )
)


class ExecutiveSummaryGenerationConsumer(Consumer):
    def __init__(self):
        self.id = f"executive_summary_generator_consumer"
        super().__init__()

    async def handle(self, ctx: HandleContext, event: BeforeHandoffToCoder) -> None:
        executive_summary = await generate_executive_summary(messages=event.messages,
                                                             executive_summary=event.executive_summary)
        if executive_summary and isinstance(executive_summary, str):
            await set_product_executive_summary(event.user_name, event.product_id, executive_summary)
        else:
            logging.exception("Invalid executive summary: " + str(executive_summary))


async def init_orchestrator(user_name: str, product_id: str) -> OrchestratorState:
    filestore, product, _ = await asyncio.gather(read_all_files_in_memory(user_name, product_id),
                                                 Product.find_one(Product.product_id == product_id),
                                                 event_bus.subscribe(BeforeHandoffToCoder,
                                                                     ExecutiveSummaryGenerationConsumer()))
    state = OrchestratorState(messages=[], executive_summary=product.executive_summary, filestore=filestore)
    save_state(user_name, product_id, state)
    return state


def load_state(user_name: str, product_id: str) -> OrchestratorState:
    """Retrieve the current state for a given user/product pair."""
    # TODO: make deep copy of state before passing it out
    return _state_store[(user_name, product_id)]


def save_state(user_name: str, product_id: str, state: OrchestratorState) -> None:
    """Persist the given state for a user/product pair."""
    _state_store[(user_name, product_id)] = state


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
async def edit_product(user_name: str, product_id: str, message: str,
                       coder_completed_callback,
                       stream_to_user_callback):
    # TODO: This duplication can be overcome by memoization, or passing state as param
    orchestrator_state = load_state(user_name, product_id)
    file_store = orchestrator_state.filestore
    update_status("Thinking...")
    orchestrator_state.messages.append(LLMMessage(role="user", content=message))
    response = await stream_user_response_or_coder(messages=orchestrator_state.messages, filestore=file_store)

    final_response = await baml_stream_and_collect_user_response(response, stream_to_user_callback)
    if isinstance(final_response, Coder):
        await event_bus.emit(
            BeforeHandoffToCoder(user_name=user_name, product_id=product_id, messages=orchestrator_state.messages,
                                 executive_summary=orchestrator_state.executive_summary))
        coder_response = await run_coder_agent(messages=orchestrator_state.messages, filestore=file_store)
        orchestrator_state.messages.append(LLMMessage(role="assistant", content=coder_response.content))
        await coder_completed_callback(user_name, product_id, file_store)
        update_status("The website is ready to be deployed. Use the 🚀 from the sidebar to deploy your website")
    elif isinstance(final_response, ResponseToUser):
        orchestrator_state.messages.append(LLMMessage(role="assistant", content=final_response.response_to_user))
    else:
        raise ValueError("Unexpected response type")


@agent_task
async def start_product(user_name: str, product_id: str, message: str,
                        coder_completed_callback, message_to_user_callback):
    t_agent = TemplateAgent(user_name, product_id)
    response = await t_agent.build_specification(message, message_to_user_callback)

    # We will only proceed to next step, if we have a website specification. Otherwise, wait for additional user input
    if isinstance(response, WebsiteSpecification):
        # TODO: This duplication can be overcome by memoization, or passing state as param, or using a class
        orchestrator_state = load_state(user_name, product_id)
        file_store = orchestrator_state.filestore
        new_spec = response.spec

        orchestrator_state.messages.append(LLMMessage(role="user", content=message))
        orchestrator_state.messages.append(LLMMessage(role="assistant", content=new_spec))
        orchestrator_state.messages.append(
            LLMMessage(role="user", content="Let's use this specification to build the website"))
        update_status("Coder is writing the code...")
        await event_bus.emit(
            BeforeHandoffToCoder(user_name=user_name, product_id=product_id, messages=orchestrator_state.messages,
                                 executive_summary=orchestrator_state.executive_summary)
        )
        coder_response = await run_coder_agent(messages=orchestrator_state.messages, filestore=file_store)
        orchestrator_state.messages.append(LLMMessage(role="assistant", content=coder_response.content))
        await coder_completed_callback(user_name, product_id, file_store)

        update_status("The website is ready to be deployed. Use the 🚀 from the sidebar to deploy your website")


async def handle_user_message(user_name: str, product_id: str, message: str,
                              coder_completed_callback, stream_to_user_callback):
    orchestrator_state = load_state(user_name, product_id)
    file_store = orchestrator_state.filestore
    if file_store.file_exists(INDEX_FILE_NAME):
        await edit_product(user_name, product_id, message, coder_completed_callback, stream_to_user_callback)
    else:
        await start_product(user_name, product_id, message, coder_completed_callback, stream_to_user_callback)


@agent_task
async def handle_file_upload(user_name: str, product_id, files: list[tuple[str, str]], message: str,
                             coder_completed_callback, stream_to_user_callback):
    image_files = []
    non_image_files = []
    for file_tuple in files:
        content_type, _ = mimetypes.guess_type(file_tuple[1])
        if content_type and content_type.startswith("image/"):
            image_files.append(file_tuple)
        else:
            non_image_files.append(file_tuple)

    try:
        uploaded_paths = []

        if non_image_files:
            non_image_paths = await asyncio.gather(*(
                upload_file(user_name=user_name, product_id=product_id, file_path=Path(file_tuple[0]),
                            file_name=file_tuple[1], description=message) for file_tuple in non_image_files))
            uploaded_paths.extend(non_image_paths)

        enriched_message = message
        if image_files:
            def _to_baml_image(file_tuple) -> Image:
                path, name = file_tuple
                content_type, _ = mimetypes.guess_type(name)
                media_type = content_type or "image/jpeg"
                return Image.from_base64(media_type, base64.b64encode(Path(path).read_bytes()).decode())

            orchestrator_state = load_state(user_name, product_id)
            messages_for_intent = orchestrator_state.messages + [
                LLMMessage(role="user", content=message,
                           images=[_to_baml_image(ft) for ft in image_files])
            ]
            upload_intent = await b.ShouldUploadToAssets(messages_for_intent)

            if upload_intent.problem:
                await stream_to_user_callback(upload_intent.problem)
                return

            if upload_intent.upload:
                image_paths = await asyncio.gather(*(
                    upload_file(user_name=user_name, product_id=product_id, file_path=Path(file_tuple[0]),
                                file_name=file_tuple[1], description=message) for file_tuple in image_files))
                uploaded_paths.extend(image_paths)
            else:
                enriched_message = (
                    f"The user uploaded images for reference: {upload_intent.image_description}\n\n{message}"
                )

        if uploaded_paths or image_files:
            if uploaded_paths:
                files_block = "\n".join(f"- {p}" for p in uploaded_paths)
                final_message = f"Here are newly uploaded files:\n{files_block}\n\n{enriched_message}"
            else:
                final_message = enriched_message
            await handle_user_message(user_name, product_id, final_message,
                                      coder_completed_callback=coder_completed_callback,
                                      stream_to_user_callback=stream_to_user_callback)
        else:
            update_status("Something went wrong uploading files. Please try again, or contact support.")
    except ValueError as e:
        update_status(str(e))
    except Exception as e:
        logging.exception("Error uploading files")
        update_status("Something went wrong while uploading the file. Try again later, or contact support.")
