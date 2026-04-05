from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from openai import Client

from breba_app.coder_agent.agent import run_coder_agent, FileStore
from breba_app.coder_agent.baml_client.types import LLMMessage
from breba_app.config import load_env
from breba_app.filesystem import in_memory_store, InMemoryFileStore
from breba_app.orchestrator import handle_user_message, save_state, OrchestratorState, handle_file_upload
from evals.loader import load_messages, load_initial_files, load_evals

load_env(".env.integration_tests")

client = Client()

EVALUATION_PROMPT = "You are evaluating correctness. Just answer the question. No comments or explanations. Just the answer."
EVALUATION_MODEL = "gpt-4.1-mini"


def _render_file(file_name: str, file_content: str):
    return f"""{file_name}
```
{file_content}
```
"""


def load_case(case_dir: Path) -> tuple[list[LLMMessage], InMemoryFileStore]:
    messages = load_messages(case_dir)

    initial = load_initial_files(case_dir)

    store = in_memory_store.from_raw_strings(initial)
    return messages, store


async def run_case(case_dir: Path, save_result_files: bool = False) -> tuple[LLMMessage, FileStore]:
    messages, store = load_case(case_dir)
    agent_response = await run_coder_agent(messages=messages, filestore=store)
    if save_result_files:
        for file_name in store.list_files():
            result_dir = case_dir / "result"
            result_dir.mkdir(parents=True, exist_ok=True)
            write_path = result_dir / file_name
            file_content = store.read_text(file_name)
            write_path.write_text(file_content)
    return agent_response, store


def combine_agent_response_with_files(agent_response: LLMMessage, store: FileStore):
    files_content = ""
    for file_name in store.list_files():
        file_content = store.read_text(file_name)
        files_content += _render_file(file_name, file_content)
    return (
        f"<project_files>"
        f"<description>\nThe following files exist in the project. Use these files to evaluate content. We don't know if the files were modified\n</description>"
        f"\n{files_content}\n</project_files>\n\n"
        f"<agent_response>\n{agent_response.content}\n</agent_response>")


async def run_evals(case_dir: Path, text: str):
    evals = load_evals(case_dir)
    for evaluation in evals:
        eval_message_content = (f"Given the following text:\n{text}\n\n"
                                f"{evaluation["question"]}\n"
                                f"Your allowed answer options: {evaluation.get("answer_options", "answer options are not restricted")}\n")
        result = client.responses.create(
            model=EVALUATION_MODEL,
            temperature=0,
            top_p=1,
            input=[
                {
                    "role": "system",
                    "content": EVALUATION_PROMPT
                },
                {
                    "role": "user",
                    "content": eval_message_content
                }
            ])
        print(eval_message_content)
        assert result.output_text.lower().strip() == evaluation["expected_answer"]


async def coder_completed_callback(_user_name: str, _product_id: str, _file_store):
    # no-op for eval; orchestrator already mutated _file_store in-place
    return


class StreamUserCallback:
    def __init__(self):
        self.sideeffect = ""

    async def __call__(self, stream_or_text):
        """
        Orchestrator passes an async iterator of chunks (baml_stream_and_collect),
        and TemplateAgent may pass plain strings depending on your implementation.
        Consume everything.
        """
        if hasattr(stream_or_text, "__aiter__"):
            async for token_sequence in stream_or_text:
                self.sideeffect = token_sequence
        else:
            # plain text (or other) - ignore
            pass


@pytest.mark.asyncio
async def test_coder_create_new_website() -> None:
    case = "modify_text"
    case_dir = Path(__file__).parent / "cases" / "orchestrator_evals" / case

    messages, store = load_case(case_dir)
    user_name = "eval_user"
    product_id = case

    save_state(user_name, product_id, OrchestratorState([], "", store))

    # Typically your case_dir/messages has at least one user message.
    last_user_msg = next(m.content for m in reversed(messages) if m.role == "user")

    stream_user_callback = StreamUserCallback()
    await handle_user_message(
        user_name=user_name,
        product_id=product_id,
        message=last_user_msg,
        coder_completed_callback=coder_completed_callback,
        stream_to_user_callback=stream_user_callback,
    )
    await run_evals(case_dir, stream_user_callback.sideeffect)


@pytest.mark.asyncio
async def test_image_upload() -> None:
    case = "upload_files"
    case_dir = Path(__file__).parent / "cases" / "orchestrator_evals" / case

    messages, store = load_case(case_dir)
    user_name = "eval_user"
    product_id = case

    save_state(user_name, product_id, OrchestratorState([], store))

    # ---- Choose the user message to send ----
    # Typically your case_dir/messages has at least one user message.
    last_user_msg = next(m.content for m in reversed(messages) if m.role == "user")

    files_dir = Path(__file__).parent / "cases" / "orchestrator_evals" / case / "assets"
    files = [(str(files_dir / "Limitations.jpeg"), "home.png"), (str(files_dir / "Goals.jpeg"), "Goals.jpeg")]

    stream_user_callback = StreamUserCallback()
    with patch(
            "breba_app.tools.upload_files.save_image_file_to_private",
            side_effect=[
                "https://example.com/file1.jpeg",
                "https://example.com/file2.jpeg",
            ]
    ) as mock_save:
        await handle_file_upload(
            user_name=user_name,
            product_id=product_id,
            files=files,
            message=last_user_msg,
            coder_completed_callback=coder_completed_callback,
            stream_to_user_callback=stream_user_callback,
        )
    mock_save.assert_called()
    await run_evals(case_dir, stream_user_callback.sideeffect)
