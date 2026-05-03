from __future__ import annotations

import logging
from typing import AsyncIterable

from baml_py import BamlStream
from baml_py.errors import BamlTimeoutError, BamlClientError

from breba_app.coder_agent.baml_client.async_client import b
from breba_app.coder_agent.baml_client.types import LLMMessage
from breba_app.config import INDEX_FILE_NAME
from breba_app.filesystem import FileStore, InMemoryFileStore, FileWrite
from breba_app.search_replace_editing import apply_search_replace_many, ApplyEditsError

logger = logging.getLogger(__name__)

NO_FILES_TO_MODIFY_MSG = "No files to modify for this request"
MAX_RETRIES = 3


def _modified_files(before: dict[str, FileWrite], after: dict[str, FileWrite]) -> list[str]:
    out: list[str] = []
    for path, after_file in after.items():
        before_file = before.get(path)
        if before_file is None or before_file.content != after_file.content:
            out.append(path)
    return sorted(out)


def _render_file(file_name: str, file_content: str) -> str:
    return f"""{file_name}
```
{file_content}
```
"""


def _render_files(files: set[str], filestore: FileStore) -> str:
    response = ""
    for file_name in files:
        if not filestore.file_exists(file_name):
            continue
        file_content = filestore.read_text(file_name)
        response += _render_file(file_name, file_content)
    return response


def _retry_err_message(e: Exception | str) -> str:
    return f"I tried to use your search and replace blocks and ran into the following errors, please fix them:\n{str(e)}"


def _files_to_edit_message(file_contents: str) -> LLMMessage:
    return LLMMessage(role="user",
                      content=f"The following files are available for editing. Do not edit any other files. You may create new files if needed.\n"
                              f"<files_available_for_editing>\n{file_contents}\n</files_available_for_editing>")


async def _get_first_word(stream: AsyncIterable[str]):
    buffer = ""
    async for token in stream:
        buffer += token
        if " " in buffer:
            # Return as soon as we see a space
            return buffer
    return buffer


async def _to_user_stream(first_msg: str, stream: AsyncIterable[str]) -> AsyncIterable[str]:
    yield first_msg
    async for msg in stream:
        yield msg


AGENTS_MD_FILE = "AGENTS.md"


async def stream_user_response_or_coder(*, messages: list[LLMMessage], filestore: FileStore) \
        -> BamlStream:
    if filestore.file_exists(INDEX_FILE_NAME):
        index_html = filestore.read_text(INDEX_FILE_NAME)
    else:
        index_html = ""
    return b.stream.UserResponseOrCoder(messages, index_html, filestore.list_files())


async def read_files_to_edit(*, original_context: list[LLMMessage], filestore: FileStore) -> tuple[str, set[str]]:
    max_depth = 5
    files_list = filestore.list_files()
    if not files_list:
        # This indicates that we just don't have files.
        return NO_FILES_TO_MODIFY_MSG, set()

    safe_context = original_context.copy()
    file_contents = ""

    seen_files = set()
    for _ in range(max_depth):
        try:
            files_response = await b.DetermineFilesToEdit(safe_context, files_list)
        except BamlTimeoutError as e:
            logger.exception("DetermineFilesToEdit timed out [%s]: %s", e.timeout_type, e)
            raise
        except BamlClientError as e:
            logger.exception("DetermineFilesToEdit client error: %s", e)
            raise

        if not files_response.files:
            # There are no new files to read for this task
            break

        files_response_set = set(files_response.files)

        new_files_set = files_response_set - seen_files

        if new_files_set:
            seen_files = seen_files | new_files_set
            file_contents += _render_files(new_files_set, filestore)
        else:
            # The new files are already in the list, no new files to add to the context
            break

        safe_context.append(LLMMessage(role="user", content=""))
        follow_up_msg = (f"Here are the file contents of the files:\n"
                         f"{file_contents}\n"
                         f"Are additional files needed to satisfy user request?\n")
        safe_context.append(LLMMessage(role="assistant", content=follow_up_msg))

    return file_contents or NO_FILES_TO_MODIFY_MSG, seen_files


async def update_executive_summary(*, messages: list[LLMMessage], filestore: FileStore) -> str | None:
    current = filestore.read_text(AGENTS_MD_FILE) if filestore.file_exists(AGENTS_MD_FILE) else ""
    index_html = filestore.read_text(INDEX_FILE_NAME) if filestore.file_exists(INDEX_FILE_NAME) else ""
    try:
        agents_md = await b.CoderNotes(messages, current, index_html)
    except BamlTimeoutError as e:
        logger.exception("CoderNotes timed out [%s]: %s", e.timeout_type, e)
        raise
    except BamlClientError as e:
        logger.exception("CoderNotes client error: %s", e)
        raise
    if agents_md and isinstance(agents_md, str) and agents_md.strip().lower() != "noop":
        filestore.write_text(AGENTS_MD_FILE, agents_md)
        return agents_md
    elif not agents_md or not isinstance(agents_md, str):
        logger.error("Invalid agents_md: %s", agents_md)
    return None


async def run_coder_agent(*, messages: list[LLMMessage], filestore: FileStore) -> LLMMessage:
    """
    Stateless agent.
    Success: returns a string listing updated files.
    Failure: returns an error string.
    """
    # TODO: use decorator to sanitize inputs with proper deepcopy
    safe_context = messages.copy()

    latest_file_contents, files_working_set = await read_files_to_edit(original_context=messages, filestore=filestore)

    before = filestore.snapshot()
    edit_store = InMemoryFileStore(before)
    file_contents_index = None

    for attempt in range(MAX_RETRIES):
        try:
            # Remove the file contents message so we can add it back with the latest file contents
            if file_contents_index:
                safe_context.pop(file_contents_index)
            safe_context.append(_files_to_edit_message(latest_file_contents))
            # This is used for removing the file contents message on retry
            file_contents_index = len(safe_context) - 1

            search_replace_text = await b.GenerateSearchReplaceBlocks(safe_context)

            safe_context.append(LLMMessage(role="assistant", content=search_replace_text))
            edits = apply_search_replace_many(edit_store, search_replace_text)
            # break on success
            break
        except BamlTimeoutError as e:
            logger.exception("GenerateSearchReplaceBlocks timed out [%s]: %s", e.timeout_type, e)
            raise
        except BamlClientError as e:
            logger.exception("GenerateSearchReplaceBlocks client error: %s", e)
            raise
        except ApplyEditsError as e:
            # Atomic behavior: reset scratchpad and do not write anything on failure
            logger.exception(f"Failed to apply code changes ({attempt} of {MAX_RETRIES})")
            edit_store = InMemoryFileStore(before)

            if attempt == MAX_RETRIES - 1:
                logger.error("All attempts to apply code")
                return LLMMessage(role="assistant",
                                  content=f"ERROR: All edit attempts failed. Try making a more specific request.")

            safe_context.append(LLMMessage(role="user", content=_retry_err_message(e)))
            latest_file_contents = _render_files(files_working_set, filestore)

    modified = _modified_files(before, edit_store.snapshot())
    if not modified:
        return LLMMessage(role="assistant", content="UPDATED_FILES:\n(none)")

    # Write back only changed/new files
    for path in modified:
        filestore.write_text(path, edit_store.read_text(path))

    return LLMMessage(role="assistant", content="UPDATED_FILES:\n" + "\n".join(f"- {p}" for p in modified))
