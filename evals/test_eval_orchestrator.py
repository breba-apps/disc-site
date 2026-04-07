from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from breba_app.chainlit_bridge import BrebaMessage, BrebaElement
from breba_app.config import load_env
from breba_app.filesystem import in_memory_store, InMemoryFileStore
from breba_app.orchestrator import handle_user_message, save_state, OrchestratorState, handle_file_upload
from evals.helpers import run_evals, StreamUserCallback
from evals.loader import load_messages, load_initial_files

load_env(".env.integration_tests")


def load_case(case_dir: Path) -> tuple[list[BrebaMessage], InMemoryFileStore]:
    messages = load_messages(case_dir)
    initial = load_initial_files(case_dir)
    store = in_memory_store.from_raw_strings(initial)
    return messages, store


def setup_orchestrator_case(case: str) -> tuple[Path, BrebaMessage, str, str, InMemoryFileStore]:
    case_dir = Path(__file__).parent / "cases" / "orchestrator_evals" / case
    messages, store = load_case(case_dir)
    user_name = "eval_user"
    save_state(user_name, case, OrchestratorState([], "", store))
    last_user_msg = next(m for m in reversed(messages) if m.role == "user")
    return case_dir, last_user_msg, user_name, case, store


async def coder_completed_callback(_user_name: str, _product_id: str, _file_store):
    return


@pytest.mark.asyncio
async def test_coder_create_new_website() -> None:
    case_dir, last_user_msg, user_name, product_id, _ = setup_orchestrator_case("modify_text")

    stream_user_callback = StreamUserCallback()
    await handle_user_message(
        user_name=user_name,
        product_id=product_id,
        message=last_user_msg,
        coder_completed_callback=coder_completed_callback,
        stream_to_user_callback=stream_user_callback,
    )
    await run_evals(case_dir, stream_user_callback.sideeffect)


def _make_image_message(content: str, assets_dir: Path) -> BrebaMessage:
    return BrebaMessage(
        role="user",
        content=content,
        elements=[
            BrebaElement(path=str(assets_dir / "Limitations.jpeg"), name="Limitations.jpeg"),
            BrebaElement(path=str(assets_dir / "Goals.jpeg"), name="Goals.jpeg"),
        ]
    )


UPLOAD_ASSETS_DIR = Path(__file__).parent / "cases" / "orchestrator_evals" / "upload_files" / "assets"


@pytest.mark.asyncio
async def test_image_upload() -> None:
    _, last_user_msg, user_name, product_id, _ = setup_orchestrator_case("upload_files")
    message = _make_image_message(last_user_msg.content, UPLOAD_ASSETS_DIR)

    with patch("breba_app.tools.upload_files.save_image_file_to_private",
               side_effect=["https://example.com/file1.jpeg", "https://example.com/file2.jpeg"]) as mock_save, \
         patch("breba_app.orchestrator.handle_user_message") as mock_handle:
        await handle_file_upload(
            user_name=user_name,
            product_id=product_id,
            message=message,
            coder_completed_callback=coder_completed_callback,
            stream_to_user_callback=StreamUserCallback(),
        )

    mock_save.assert_called()
    mock_handle.assert_called_once()
    forwarded_message: BrebaMessage = mock_handle.call_args.args[2]
    assert "https://example.com/file1.jpeg" in forwarded_message.content
    assert "https://example.com/file2.jpeg" in forwarded_message.content
    assert len(forwarded_message.elements) == 2


@pytest.mark.asyncio
async def test_image_interpret() -> None:
    _, last_user_msg, user_name, product_id, _ = setup_orchestrator_case("interpret_images")
    message = _make_image_message(last_user_msg.content, UPLOAD_ASSETS_DIR)

    with patch("breba_app.tools.upload_files.save_image_file_to_private") as mock_save, \
         patch("breba_app.orchestrator.handle_user_message") as mock_handle:
        await handle_file_upload(
            user_name=user_name,
            product_id=product_id,
            message=message,
            coder_completed_callback=coder_completed_callback,
            stream_to_user_callback=StreamUserCallback(),
        )

    mock_save.assert_not_called()
    mock_handle.assert_called_once()
    forwarded_message: BrebaMessage = mock_handle.call_args.args[2]
    assert forwarded_message.content == last_user_msg.content
    assert len(forwarded_message.elements) == 2
