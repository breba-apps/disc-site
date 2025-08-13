import difflib

from unidiff import PatchSet


class PatchApplyError(Exception):
    pass


def get_diff(old_text: str, new_text: str):
    diff = difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile='before',
        tofile='after',
        lineterm=''
    )
    return "\n".join(diff)


def apply_diff(original_text: str, diff_text: str) -> str:
    original_lines = original_text.splitlines(keepends=True)
    patch = PatchSet(diff_text)

    if len(patch) != 1:
        raise PatchApplyError("Only single-file diffs are supported.")

    file_patch = patch[0]
    patched_lines = []
    src_idx = 0  # cursor in original_lines

    for hunk in file_patch:
        hunk_start = hunk.source_start - 1  # 0-based

        # copy lines before the hunk
        if src_idx > hunk_start:
            raise PatchApplyError(
                f"Hunk overlaps earlier edits (src_idx={src_idx}, hunk_start={hunk_start})."
            )
        patched_lines.extend(original_lines[src_idx:hunk_start])
        src_idx = hunk_start

        # apply the hunk with strict checks
        for line in hunk:
            if line.is_context:
                if src_idx >= len(original_lines):
                    raise PatchApplyError("Context beyond end of file.")
                if original_lines[src_idx] != line.value:
                    raise PatchApplyError(
                        f"Context mismatch at line {src_idx + 1}:\n"
                        f"  Expected: {line.value!r}\n"
                        f"  Actual  : {original_lines[src_idx]!r}"
                    )
                patched_lines.append(original_lines[src_idx])
                src_idx += 1

            elif line.is_removed:
                if src_idx >= len(original_lines):
                    raise PatchApplyError("Removal beyond end of file.")
                if original_lines[src_idx] != line.value:
                    raise PatchApplyError(
                        f"Remove mismatch at line {src_idx + 1}:\n"
                        f"  Expected: {line.value!r}\n"
                        f"  Actual  : {original_lines[src_idx]!r}"
                    )
                # skip (remove) this line from output
                src_idx += 1

            elif line.is_added:
                # added lines don't advance src_idx
                patched_lines.append(line.value)

            else:
                raise PatchApplyError("Unknown hunk line type.")

    # append the rest of the original file
    patched_lines.extend(original_lines[src_idx:])
    return ''.join(patched_lines)

# old = Path("temp.html").read_text()
# new_text = Path("temp2.html").read_text()
# diff = get_html_diff(old, new_text)
#
# print("Diff:")
# print(diff)
#
# bad = Path("temp.html.bad").read_text()
# patched = apply_unified_diff_to_text_safe(bad, diff)
#
# print("Patched:")
# Path("temp3.html").write_text(patched)
#
