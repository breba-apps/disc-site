from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breba_app.llm_utils import BrebaMessage, BrebaElement
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
    save_state(user_name, case, OrchestratorState([], store))
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


@pytest.mark.asyncio
async def test_favicon_written_to_filestore() -> None:
    """favicon.ico bypasses CDN and lands directly in the project filestore."""
    _, last_user_msg, user_name, product_id, store = setup_orchestrator_case("upload_files")
    favicon_path = UPLOAD_ASSETS_DIR / "favicon.ico"
    message = BrebaMessage(
        role="user",
        content=last_user_msg.content,
        elements=[BrebaElement(path=str(favicon_path), name="favicon.ico")],
    )

    with patch("breba_app.tools.upload_files.save_image_file_to_private") as mock_save, \
         patch("breba_app.orchestrator.handle_user_message") as mock_handle:
        await handle_file_upload(
            user_name=user_name,
            product_id=product_id,
            message=message,
            coder_completed_callback=coder_completed_callback,
            stream_to_user_callback=StreamUserCallback(),
        )

    # Never uploaded to CDN
    mock_save.assert_not_called()
    # Coder was invoked
    mock_handle.assert_called_once()
    # File is in the filestore with correct bytes
    assert store.file_exists("favicon.ico")
    assert store._files["favicon.ico"].content == favicon_path.read_bytes()
    # Message tells the coder about the project-root file
    forwarded_message: BrebaMessage = mock_handle.call_args.args[2]
    assert "favicon.ico" in forwarded_message.content
    assert "project files added to the website root" in forwarded_message.content.lower()
    # favicon.ico must not be in elements — its MIME type would be rejected by the LLM
    assert all(el.name != "favicon.ico" for el in forwarded_message.elements)


@pytest.mark.asyncio
async def test_favicon_mixed_with_image_upload() -> None:
    """favicon.ico goes to filestore; regular images still go to CDN."""
    _, last_user_msg, user_name, product_id, store = setup_orchestrator_case("upload_files")
    favicon_path = UPLOAD_ASSETS_DIR / "favicon.ico"
    message = BrebaMessage(
        role="user",
        content=last_user_msg.content,
        elements=[
            BrebaElement(path=str(favicon_path), name="favicon.ico"),
            BrebaElement(path=str(UPLOAD_ASSETS_DIR / "Limitations.jpeg"), name="Limitations.jpeg"),
        ],
    )

    upload_intent = MagicMock()
    upload_intent.problem = None
    upload_intent.upload = True

    with patch("breba_app.tools.upload_files.save_image_file_to_private",
               side_effect=["https://example.com/Limitations.jpeg"]) as mock_save, \
         patch("breba_app.orchestrator.b.ShouldUploadToAssets", new=AsyncMock(return_value=upload_intent)), \
         patch("breba_app.orchestrator.handle_user_message") as mock_handle:
        await handle_file_upload(
            user_name=user_name,
            product_id=product_id,
            message=message,
            coder_completed_callback=coder_completed_callback,
            stream_to_user_callback=StreamUserCallback(),
        )

    # Only the JPEG was uploaded to CDN
    mock_save.assert_called_once()
    assert store.file_exists("favicon.ico")
    forwarded_message: BrebaMessage = mock_handle.call_args.args[2]
    assert "favicon.ico" in forwarded_message.content
    assert "https://example.com/Limitations.jpeg" in forwarded_message.content
