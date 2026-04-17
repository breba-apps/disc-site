import difflib
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from breba_app.filesystem import FileStore

logger = logging.getLogger(__name__)

HEAD = r"^<{5,9} SEARCH>?\s*$"
DIVIDER = r"^={5,9}\s*$"
UPDATED = r"^>{5,9} REPLACE\s*$"

HEAD_ERR = "<<<<<<< SEARCH"
DIVIDER_ERR = "======="
UPDATED_ERR = ">>>>>>> REPLACE"

DEFAULT_FENCE = ("`" * 3, "`" * 3)

TRIPLE_BACKTICKS = "`" * 3

missing_filename_err = (
    "Bad/missing filename. The filename must be alone on the line before the opening fence"
    " {fence[0]}"
)


@dataclass
class EditRequest:
    path: str
    search: str
    replace: str


class ApplyEditsError(Exception):
    def __init__(self, message, failed, passed, updated_edits):
        super().__init__(message)
        self.failed = failed
        self.passed = passed
        self.updated_edits = updated_edits


def strip_filename(filename, fence):
    filename = filename.strip()

    if filename == "...":
        return

    start_fence = fence[0]
    if filename.startswith(start_fence):
        candidate = filename[len(start_fence):]
        if candidate and ("." in candidate or "/" in candidate):
            return candidate
        return

    if filename.startswith(TRIPLE_BACKTICKS):
        candidate = filename[len(TRIPLE_BACKTICKS):]
        if candidate and ("." in candidate or "/" in candidate):
            return candidate
        return

    filename = filename.rstrip(":")
    filename = filename.lstrip("#")
    filename = filename.strip()
    filename = filename.strip("`")
    filename = filename.strip("*")

    # https://github.com/Aider-AI/aider/issues/1158
    # filename = filename.replace("\\_", "_")

    return filename


def find_filename(lines, fence, valid_fnames):
    """
    Deepseek Coder v2 has been doing this:


     ```python
    word_count.py
    ```
    ```python
    <<<<<<< SEARCH
    ...

    This is a more flexible search back for filenames.
    """

    if valid_fnames is None:
        valid_fnames = []

    # Go back through the 3 preceding lines
    lines.reverse()
    lines = lines[:3]

    filenames = []
    for line in lines:
        # If we find a filename, done
        filename = strip_filename(line, fence)
        if filename:
            filenames.append(filename)

        # Only continue as long as we keep seeing fences
        if not line.startswith(fence[0]) and not line.startswith(TRIPLE_BACKTICKS):
            break

    if not filenames:
        return

    # pick the *best* filename found

    # Check for exact match first
    for fname in filenames:
        if fname in valid_fnames:
            return fname

    # Check for partial match (basename match)
    for fname in filenames:
        for vfn in valid_fnames:
            if fname == Path(vfn).name:
                return vfn

    # Perform fuzzy matching with valid_fnames
    for fname in filenames:
        close_matches = difflib.get_close_matches(fname, valid_fnames, n=1, cutoff=0.8)
        if len(close_matches) == 1:
            return close_matches[0]

    # If no fuzzy match, look for a file w/extension
    for fname in filenames:
        if "." in fname:
            return fname

    if filenames:
        return filenames[0]


def normalize_marker_line(line: str, fence: str) -> str:
    s = line.strip()
    if fence:
        s = re.sub(rf"\s*{re.escape(fence)}\s*$", "", s)
    return s


def update_blocks_gen(content, fence=DEFAULT_FENCE, valid_fnames=None):
    lines = content.splitlines(keepends=True)
    i = 0
    current_filename = None

    head_pattern = re.compile(HEAD)
    divider_pattern = re.compile(DIVIDER)
    updated_pattern = re.compile(UPDATED)

    while i < len(lines):
        line = lines[i]

        # Check for SEARCH/REPLACE blocks
        if head_pattern.match(line.strip()):
            try:
                # if next line after HEAD exists and is DIVIDER, it's a new file
                if i + 1 < len(lines) and divider_pattern.match(lines[i + 1].strip()):
                    filename = find_filename(lines[max(0, i - 3): i], fence, None)
                else:
                    filename = find_filename(lines[max(0, i - 3): i], fence, valid_fnames)

                if not filename:
                    if current_filename:
                        filename = current_filename
                    else:
                        raise ValueError(missing_filename_err.format(fence=fence))

                current_filename = filename

                original_text = []
                i += 1
                while i < len(lines) and not divider_pattern.match(lines[i].strip()):
                    original_text.append(lines[i])
                    i += 1

                if i >= len(lines) or not divider_pattern.match(lines[i].strip()):
                    raise ValueError(f"Expected `{DIVIDER_ERR}`")

                updated_text = []
                i += 1
                while i < len(lines) and not (
                        updated_pattern.match(normalize_marker_line(lines[i], fence[1]))
                        or divider_pattern.match(lines[i].strip())
                ):
                    updated_text.append(lines[i])
                    i += 1

                if i >= len(lines) or not (
                        updated_pattern.match(normalize_marker_line(lines[i], fence[1]))
                        or divider_pattern.match(lines[i].strip())
                ):
                    raise ValueError(f"Expected `{UPDATED_ERR}` or `{DIVIDER_ERR}`")

                yield EditRequest(filename, "".join(original_text), "".join(updated_text))

            except ValueError as e:
                processed = "".join(lines[: i + 1])
                err = e.args[0]
                raise ValueError(f"{processed}\n^^^ {err}")

        i += 1


def find_original_update_blocks(content, fence=DEFAULT_FENCE, valid_fnames=None):
    lines = content.splitlines(keepends=True)
    i = 0
    current_filename = None

    head_pattern = re.compile(HEAD)
    divider_pattern = re.compile(DIVIDER)
    updated_pattern = re.compile(UPDATED)

    while i < len(lines):
        line = lines[i]

        # Check for SEARCH/REPLACE blocks
        if head_pattern.match(line.strip()):
            try:
                # if next line after HEAD exists and is DIVIDER, it's a new file
                if i + 1 < len(lines) and divider_pattern.match(lines[i + 1].strip()):
                    filename = find_filename(lines[max(0, i - 3): i], fence, None)
                else:
                    filename = find_filename(lines[max(0, i - 3): i], fence, valid_fnames)

                if not filename:
                    if current_filename:
                        filename = current_filename
                    else:
                        raise ValueError(missing_filename_err.format(fence=fence))

                current_filename = filename

                original_text = []
                i += 1
                while i < len(lines) and not divider_pattern.match(lines[i].strip()):
                    original_text.append(lines[i])
                    i += 1

                if i >= len(lines) or not divider_pattern.match(lines[i].strip()):
                    raise ValueError(f"Expected `{DIVIDER_ERR}`")

                updated_text = []
                i += 1
                while i < len(lines) and not (
                        updated_pattern.match(lines[i].strip())
                        or divider_pattern.match(lines[i].strip())
                ):
                    updated_text.append(lines[i])
                    i += 1

                if i >= len(lines) or not (
                        updated_pattern.match(lines[i].strip())
                        or divider_pattern.match(lines[i].strip())
                ):
                    raise ValueError(f"Expected `{UPDATED_ERR}` or `{DIVIDER_ERR}`")

                yield filename, "".join(original_text), "".join(updated_text)

            except ValueError as e:
                processed = "".join(lines[: i + 1])
                err = e.args[0]
                raise ValueError(f"{processed}\n^^^ {err}")

        i += 1


def strip_quoted_wrapping(res, fname=None, fence=DEFAULT_FENCE):
    """
    Given an input string which may have extra "wrapping" around it, remove the wrapping.
    For example:

    filename.ext
    ```
    We just want this content
    Not the filename and triple quotes
    ```
    """
    if not res:
        return res

    res = res.splitlines()

    if fname and res[0].strip().endswith(Path(fname).name):
        res = res[1:]

    if res[0].startswith(fence[0]) and res[-1].startswith(fence[1]):
        res = res[1:-1]

    res = "\n".join(res)
    if res and res[-1] != "\n":
        res += "\n"

    return res


def prep(content):
    if content and not content.endswith("\n"):
        content += "\n"
    lines = content.splitlines(keepends=True)
    return content, lines


def perfect_replace(whole_lines, part_lines, replace_lines):
    part_tup = tuple(part_lines)
    part_len = len(part_lines)

    for i in range(len(whole_lines) - part_len + 1):
        whole_tup = tuple(whole_lines[i: i + part_len])
        if part_tup == whole_tup:
            res = whole_lines[:i] + replace_lines + whole_lines[i + part_len:]
            return "".join(res)


def match_but_for_leading_whitespace(whole_lines, part_lines):
    num = len(whole_lines)

    # does the non-whitespace all agree?
    if not all(whole_lines[i].lstrip() == part_lines[i].lstrip() for i in range(num)):
        return

    # are they all offset the same?
    add = set(
        whole_lines[i][: len(whole_lines[i]) - len(part_lines[i])]
        for i in range(num)
        if whole_lines[i].strip()
    )

    if len(add) != 1:
        return

    return add.pop()


def replace_part_with_missing_leading_whitespace(whole_lines, part_lines, replace_lines):
    # GPT often messes up leading whitespace.
    # It usually does it uniformly across the ORIG and UPD blocks.
    # Either omitting all leading whitespace, or including only some of it.

    # Outdent everything in part_lines and replace_lines by the max fixed amount possible
    leading = [len(p) - len(p.lstrip()) for p in part_lines if p.strip()] + [
        len(p) - len(p.lstrip()) for p in replace_lines if p.strip()
    ]

    if leading and min(leading):
        num_leading = min(leading)
        part_lines = [p[num_leading:] if p.strip() else p for p in part_lines]
        replace_lines = [p[num_leading:] if p.strip() else p for p in replace_lines]

    # can we find an exact match not including the leading whitespace
    num_part_lines = len(part_lines)

    for i in range(len(whole_lines) - num_part_lines + 1):
        add_leading = match_but_for_leading_whitespace(
            whole_lines[i: i + num_part_lines], part_lines
        )

        if add_leading is None:
            continue

        replace_lines = [add_leading + rline if rline.strip() else rline for rline in replace_lines]
        whole_lines = whole_lines[:i] + replace_lines + whole_lines[i + num_part_lines:]
        return "".join(whole_lines)

    return None


def perfect_or_whitespace(whole_lines, part_lines, replace_lines):
    # Try for a perfect match
    res = perfect_replace(whole_lines, part_lines, replace_lines)
    if res:
        return res

    # Try being flexible about leading whitespace
    res = replace_part_with_missing_leading_whitespace(whole_lines, part_lines, replace_lines)
    if res:
        return res


def try_dotdotdots(whole, part, replace):
    """
    See if the edit block has ... lines.
    If not, return none.

    If yes, try and do a perfect edit with the ... chunks.
    If there's a mismatch or otherwise imperfect edit, raise ValueError.

    If perfect edit succeeds, return the updated whole.
    """

    dots_re = re.compile(r"(^\s*\.\.\.\n)", re.MULTILINE | re.DOTALL)

    part_pieces = re.split(dots_re, part)
    replace_pieces = re.split(dots_re, replace)

    if len(part_pieces) != len(replace_pieces):
        raise ValueError("Unpaired ... in SEARCH/REPLACE block")

    if len(part_pieces) == 1:
        # no dots in this edit block, just return None
        return

    # Compare odd strings in part_pieces and replace_pieces
    all_dots_match = all(part_pieces[i] == replace_pieces[i] for i in range(1, len(part_pieces), 2))

    if not all_dots_match:
        raise ValueError("Unmatched ... in SEARCH/REPLACE block")

    part_pieces = [part_pieces[i] for i in range(0, len(part_pieces), 2)]
    replace_pieces = [replace_pieces[i] for i in range(0, len(replace_pieces), 2)]

    pairs = zip(part_pieces, replace_pieces)
    for part, replace in pairs:
        if not part and not replace:
            continue

        if not part and replace:
            if not whole.endswith("\n"):
                whole += "\n"
            whole += replace
            continue

        if whole.count(part) == 0:
            raise ValueError
        if whole.count(part) > 1:
            raise ValueError

        whole = whole.replace(part, replace, 1)

    return whole


def replace_most_similar_chunk(whole, part, replace):
    """Best efforts to find the `part` lines in `whole` and replace them with `replace`"""

    whole, whole_lines = prep(whole)
    part, part_lines = prep(part)
    replace, replace_lines = prep(replace)

    res = perfect_or_whitespace(whole_lines, part_lines, replace_lines)
    if res:
        return res

    # drop leading empty line, GPT sometimes adds them spuriously (issue #25)
    if len(part_lines) > 2 and not part_lines[0].strip():
        skip_blank_line_part_lines = part_lines[1:]
        res = perfect_or_whitespace(whole_lines, skip_blank_line_part_lines, replace_lines)
        if res:
            return res

    # Try to handle when it elides code with ...
    try:
        res = try_dotdotdots(whole, part, replace)
        if res:
            return res
    except ValueError:
        pass

    return


def do_replace(content, before_text, after_text):
    # Don't strip whitespace from before_text or after_text because we want to preserve whitespace for comparison
    before_text = strip_quoted_wrapping(before_text)
    after_text = strip_quoted_wrapping(after_text)

    if not content and before_text.strip():
        raise ValueError(f"Content is empty, but we are attempting to find:\n{before_text}")

    if not before_text.strip():
        # append to existing file, or start a new file
        new_content = content + after_text
    else:
        new_content = replace_most_similar_chunk(content, before_text, after_text)

    return new_content


def find_similar_lines(search_lines, content_lines, threshold=0.6):
    search_lines = search_lines.splitlines()
    content_lines = content_lines.splitlines()

    best_ratio = 0
    best_match = None

    for i in range(len(content_lines) - len(search_lines) + 1):
        chunk = content_lines[i: i + len(search_lines)]
        ratio = SequenceMatcher(None, search_lines, chunk).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = chunk
            best_match_i = i

    if best_ratio < threshold:
        return ""

    if best_match[0] == search_lines[0] and best_match[-1] == search_lines[-1]:
        return "\n".join(best_match)

    N = 5
    best_match_end = min(len(content_lines), best_match_i + len(search_lines) + N)
    best_match_i = max(0, best_match_i - N)

    best = content_lines[best_match_i:best_match_end]
    return "\n".join(best)


def default_failed_match_message(edit: EditRequest, content: str, fence=DEFAULT_FENCE) -> str:
    error_message = f"""
## SearchReplaceNoExactMatch: This SEARCH block failed to exactly match lines in
{edit.path}
{HEAD_ERR}
{edit.search}{DIVIDER_ERR}
{edit.replace}{UPDATED_ERR}
"""
    did_you_mean = find_similar_lines(edit.search, content)
    if did_you_mean:
        error_message += f"""Did you mean to match some of these actual lines from {edit.path}?
{fence[0]}
{did_you_mean}
{fence[1]}
"""

    if edit.replace in content and edit.replace:
        error_message += f"Are you sure you need this SEARCH/REPLACE block? \n The REPLACE lines are already in {edit.path}!"

    return error_message


def apply_edits_many(filestore: FileStore, edits: list[EditRequest], fence=DEFAULT_FENCE) -> list[EditRequest]:
    if not edits:
        raise ValueError("No edits found")

    failed = []
    passed = []
    updated_edits = []

    for edit in edits:
        if edit.search:
            try:
                content = filestore.read_text(edit.path)
                # make sure to use update file contents to iteratively apply edits
                new_content = do_replace(content, edit.search, edit.replace)
                if new_content:
                    filestore.write_text(edit.path, new_content)
                    passed.append(edit)
                else:
                    logger.error(f"Failed to match {edit.search} in {content}")
                    error_message = default_failed_match_message(edit, content)
                    failed.append(error_message)
            except FileNotFoundError:
                failed.append(f"File not found: {edit.path}")
            except ValueError as e:
                failed.append(f"{e}")

        else:
            # For new files or when appending we simply don't have a search block
            if edit.replace:
                if filestore.file_exists(edit.path):
                    # appending to file
                    filestore.write_text(edit.path, filestore.read_text(edit.path) + edit.replace)
                else:
                    # new file
                    filestore.write_text(edit.path, edit.replace)
            # If there is no replace block, we swallow the error because ignoring it is the best course of action
            passed.append(edit)

        updated_edits.append(edit)

    if not failed:
        return updated_edits

    blocks = "block" if len(failed) == 1 else "blocks"

    res = f"# {len(failed)} SEARCH/REPLACE {blocks} failed to match!\n"
    for message in failed:
        res += f"{message}\n\n"

    res += (
        "The SEARCH section must exactly match an existing block of lines including all white"
        " space, comments, indentation, docstrings, etc\n"
    )
    if passed:
        pblocks = "block" if len(passed) == 1 else "blocks"
        res += f"""
# The other {len(passed)} SEARCH/REPLACE {pblocks} were applied successfully.
Don't re-send them.
Just reply with fixed versions of the {blocks} above that failed to match. You MUST attempt to fix the errors!
"""
    raise ApplyEditsError(
        message=res,
        failed=failed,
        passed=passed,
        updated_edits=updated_edits,
    )


def apply_search_replace_many(filestore: FileStore, search_replace_text: str) -> list[str]:
    """
    This method is used to apply search and replace blocks to many files
    :param filestore: FileStore containing the files to modify
    :param search_replace_text: AI generated list of search and replace blocks to apply
    :return: list of applied edits and modified files
    """
    edits = list(update_blocks_gen(search_replace_text))
    logger.info(f"Found {len(edits)} edits")

    if not edits:
        # Probably need to raise ApplyEditsError because this could be recoverable
        raise ValueError(f"No edits found in the following search and replace pattern:\n{search_replace_text}")

    applied_edits = apply_edits_many(filestore, edits)
    return [edit.path for edit in applied_edits]
