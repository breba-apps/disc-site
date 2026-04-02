from __future__ import annotations

from pathlib import Path

import pytest
from openai import Client

from breba_app.coder_agent.agent import run_coder_agent, FileStore
from breba_app.coder_agent.baml_client.types import LLMMessage
from breba_app.config import load_env
from breba_app.filesystem import in_memory_store
from evals.loader import load_messages, load_initial_files, load_evals

load_env()

client = Client()

EVALUATION_PROMPT = "You are evaluating correctness. Just answer the question. No comments or explanations. Just the answer."
EVALUATION_MODEL = "gpt-4.1-mini"


def _render_file(file_name: str, file_content: str):
    return f"""{file_name}
```
{file_content}
```
"""


def load_case(case_dir: Path) -> tuple[list[LLMMessage], FileStore]:
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
        eval_message_content = (f"#Given the following text:\n{text}\n\n"
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


@pytest.mark.asyncio
async def test_coder_create_new_website() -> None:
    case_dir = Path(__file__).parent / "cases" / "coder_evals" / "create_hello_world"

    messages, store = load_case(case_dir)
    agent_response = await run_coder_agent(messages=messages, filestore=store)
    combined_agent_response = combine_agent_response_with_files(agent_response, store)
    await run_evals(case_dir, combined_agent_response)


@pytest.mark.asyncio
async def test_coder_create_new_website_with_bootstrap() -> None:
    case_dir = Path(__file__).parent / "cases" / "coder_evals" / "coder_evals" / "create_hello_world_bootstrap"

    messages, store = load_case(case_dir)
    agent_response = await run_coder_agent(messages=messages, filestore=store)
    combined_agent_response = combine_agent_response_with_files(agent_response, store)
    await run_evals(case_dir, combined_agent_response)


@pytest.mark.asyncio
async def test_coder_modify_font_color() -> None:
    case_dir = Path(__file__).parent / "cases" / "coder_evals" / "modify_font_color"

    messages, store = load_case(case_dir)
    agent_response = await run_coder_agent(messages=messages, filestore=store)
    combined_agent_response = combine_agent_response_with_files(agent_response, store)
    await run_evals(case_dir, combined_agent_response)


@pytest.mark.asyncio
async def test_coder_modify_text() -> None:
    case_dir = Path(__file__).parent / "cases" / "coder_evals" / "modify_text"

    messages, store = load_case(case_dir)
    agent_response = await run_coder_agent(messages=messages, filestore=store)
    combined_agent_response = combine_agent_response_with_files(agent_response, store)
    await run_evals(case_dir, combined_agent_response)


@pytest.mark.asyncio
async def test_coder_modify_text_style_behavior() -> None:
    case_dir = Path(__file__).parent / "cases" / "coder_evals" / "modify_text_style_behavior"

    messages, store = load_case(case_dir)
    agent_response = await run_coder_agent(messages=messages, filestore=store)
    combined_agent_response = combine_agent_response_with_files(agent_response, store)
    await run_evals(case_dir, combined_agent_response)


@pytest.mark.asyncio
async def test_coder_add_navbar() -> None:
    case_dir = Path(__file__).parent / "cases" / "coder_evals" / "add_navbar"

    agent_response, store = await run_case(case_dir)

    combined_agent_response = combine_agent_response_with_files(agent_response, store)
    await run_evals(case_dir, combined_agent_response)
