import pytest

from breba_app.builder import build
from breba_app.filesystem.in_memory_store import from_raw_strings


# ── helpers ──────────────────────────────────────────────────────────────────

def store(files: dict[str, str]):
    return from_raw_strings(files)


def built_paths(filestore):
    return set(build(filestore).list_files())


def built_text(filestore, path):
    return build(filestore).read_text(path)


# ── output file inclusion / exclusion ────────────────────────────────────────

def test_page_html_is_emitted():
    fs = store({"index.html": "<h1>Hello</h1>"})
    assert "index.html" in built_paths(fs)


def test_component_html_is_not_emitted():
    fs = store({"components/navbar.html": "<nav>Nav</nav>"})
    assert "components/navbar.html" not in built_paths(fs)


def test_component_css_is_emitted():
    fs = store({"components/navbar.css": "nav { color: red; }"})
    assert "components/navbar.css" in built_paths(fs)


def test_component_js_is_emitted():
    fs = store({"components/navbar.js": "console.log('nav')"})
    assert "components/navbar.js" in built_paths(fs)


def test_meta_files_are_not_emitted():
    fs = store({"index.html": "<h1>Hi</h1>", "spec.txt": "spec", "AGENTS.md": "notes"})
    paths = built_paths(fs)
    assert "spec.txt" not in paths
    assert "AGENTS.md" not in paths
    assert "index.html" in paths


def test_non_html_assets_are_emitted():
    fs = store({"index.html": "<h1>Hi</h1>", "css/styles.css": "body{}", "js/main.js": "// js"})
    paths = built_paths(fs)
    assert "css/styles.css" in paths
    assert "js/main.js" in paths


# ── jinja rendering ───────────────────────────────────────────────────────────

def test_plain_html_passes_through_unchanged():
    html = "<html><body><p>Hello</p></body></html>"
    fs = store({"index.html": html})
    assert built_text(fs, "index.html") == html


def test_include_component_in_page():
    fs = store({
        "index.html": '<div>{% include "components/navbar.html" %}</div>',
        "components/navbar.html": "<nav>Nav</nav>",
    })
    assert built_text(fs, "index.html") == "<div><nav>Nav</nav></div>"


def test_nested_component_composition():
    """A component can include another component."""
    fs = store({
        "index.html": '{% include "components/navbar.html" %}',
        "components/navbar.html": '<nav>{% include "components/logo.html" %}</nav>',
        "components/logo.html": "<span>Logo</span>",
    })
    assert built_text(fs, "index.html") == "<nav><span>Logo</span></nav>"


def test_template_inheritance():
    fs = store({
        "base.html": "<html><body>{% block content %}{% endblock %}</body></html>",
        "index.html": '{% extends "base.html" %}{% block content %}<main>Home</main>{% endblock %}',
    })
    assert built_text(fs, "index.html") == "<html><body><main>Home</main></body></html>"


def test_multiple_pages_share_component():
    fs = store({
        "index.html": '{% include "components/footer.html" %}<main>Home</main>',
        "about.html": '{% include "components/footer.html" %}<main>About</main>',
        "components/footer.html": "<footer>Footer</footer>",
    })
    result = build(fs)
    assert "<footer>Footer</footer>" in result.read_text("index.html")
    assert "<footer>Footer</footer>" in result.read_text("about.html")


def test_page_in_subdirectory_is_rendered():
    fs = store({"about/index.html": "<p>About</p>"})
    assert "about/index.html" in built_paths(fs)


def test_subdirectory_page_can_include_component():
    fs = store({
        "about/index.html": '{% include "components/navbar.html" %}<p>About</p>',
        "components/navbar.html": "<nav>Nav</nav>",
    })
    assert built_text(fs, "about/index.html") == "<nav>Nav</nav><p>About</p>"


# ── error handling ────────────────────────────────────────────────────────────

def test_missing_include_raises():
    fs = store({"index.html": '{% include "components/missing.html" %}'})
    with pytest.raises(RuntimeError, match="index.html"):
        build(fs)


def test_syntax_error_raises():
    fs = store({"index.html": "{% if %}"})
    with pytest.raises(RuntimeError, match="index.html"):
        build(fs)
