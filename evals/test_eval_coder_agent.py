from __future__ import annotations

from pathlib import Path

import pytest

from breba_app.coder_agent.agent import run_coder_agent, FileStore
from breba_app.coder_agent.baml_client.types import LLMMessage
from breba_app.chainlit_bridge import BrebaMessage

from breba_app.config import load_env
from breba_app.filesystem import in_memory_store
from evals.helpers import combine_agent_response_with_files, run_evals
from evals.loader import load_messages, load_initial_files

load_env(".env.integration_tests")


def load_case(case_dir: Path) -> tuple[list[BrebaMessage], FileStore]:
    messages = load_messages(case_dir)
    initial = load_initial_files(case_dir)
    store = in_memory_store.from_raw_strings(initial)
    return messages, store


async def run_case(case_dir: Path) -> tuple[LLMMessage, FileStore]:
    messages, store = load_case(case_dir)
    baml_messages = [m.to_baml_message() for m in messages]
    agent_response = await run_coder_agent(messages=baml_messages, filestore=store)
    return agent_response, store


async def run_coder_eval(case_dir: Path):
    agent_response, store = await run_case(case_dir)
    combined = combine_agent_response_with_files(agent_response, store)
    await run_evals(case_dir, combined)


@pytest.mark.asyncio
async def test_coder_create_new_website() -> None:
    await run_coder_eval(Path(__file__).parent / "cases" / "coder_evals" / "create_hello_world")


@pytest.mark.asyncio
async def test_coder_create_new_website_with_bootstrap() -> None:
    await run_coder_eval(Path(__file__).parent / "cases" / "coder_evals" / "create_hello_world_bootstrap")


@pytest.mark.asyncio
async def test_coder_modify_font_color() -> None:
    await run_coder_eval(Path(__file__).parent / "cases" / "coder_evals" / "modify_font_color")


@pytest.mark.asyncio
async def test_coder_modify_text() -> None:
    await run_coder_eval(Path(__file__).parent / "cases" / "coder_evals" / "modify_text")


@pytest.mark.asyncio
async def test_coder_modify_text_style_behavior() -> None:
    await run_coder_eval(Path(__file__).parent / "cases" / "coder_evals" / "modify_text_style_behavior")


@pytest.mark.asyncio
async def test_coder_add_navbar() -> None:
    await run_coder_eval(Path(__file__).parent / "cases" / "coder_evals" / "add_navbar")
