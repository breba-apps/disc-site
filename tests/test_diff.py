from pathlib import Path

import pytest

from breba_app.diff import apply_diff, get_diff, PatchApplyError


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    # Adjust if your tests live elsewhere
    return Path(__file__).parent / "fixtures"


def read_text_normalized(p: Path) -> str:
    # Normalize to LF regardless of file's native line endings
    return "\n".join(p.read_text().splitlines())


@pytest.fixture(scope="session")
def original_html(fixtures_dir) -> str:
    return read_text_normalized(fixtures_dir / "original.html")


@pytest.fixture(scope="session")
def modified_html(fixtures_dir) -> str:
    return read_text_normalized(fixtures_dir / "modified.html")


def normalize_line_endings(text):
    return "\n".join(text.splitlines())


# Helper function to generate a diff
@pytest.fixture
def valid_diff(original_html, modified_html):
    return get_diff(normalize_line_endings(original_html), normalize_line_endings(modified_html))


@pytest.fixture
def invalid_diff():
    return "--- invalid diff ---"


# Test cases

def test_apply_diff_correct(original_html, modified_html, valid_diff):
    result = apply_diff(original_html, valid_diff)
    assert result == modified_html


def test_apply_diff_context_not_found(original_html, valid_diff):
    modified_content = original_html.replace("<h1>Hello World</h1>", "<h1>Hi Universe</h1>")
    with pytest.raises(PatchApplyError):
        apply_diff(modified_content, valid_diff)


def test_apply_diff_add_remove_not_found(original_html, valid_diff):
    modified_content = original_html.replace("<p>This is the original HTML content.</p>", "<p>Changed content.</p>")
    with pytest.raises(PatchApplyError):
        apply_diff(modified_content, valid_diff)


def test_apply_diff_invalid_diff(original_html, invalid_diff):
    with pytest.raises(PatchApplyError):
        apply_diff(original_html, invalid_diff)


def test_generated_diff_format(valid_diff):
    # Print the generated diff for inspection
    print("Generated Diff:\n", valid_diff)
    # Check that the diff contains expected context lines
    assert "<html lang=\"en\">" in valid_diff
    assert "<head>" in valid_diff
    assert "<body>" in valid_diff
