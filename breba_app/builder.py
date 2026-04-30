import logging

from jinja2 import BaseLoader, Environment, TemplateNotFound

from breba_app.filesystem import FileStore, InMemoryFileStore

logger = logging.getLogger(__name__)

# Files that are internal metadata and should never appear in build output
_META_FILES = {"spec.txt", "AGENTS.md"}

# HTML component partials live here — included by pages, never emitted standalone
COMPONENTS_DIR = "components/"


class FileStoreLoader(BaseLoader):
    """Jinja2 loader that reads templates directly from a FileStore."""

    def __init__(self, filestore: FileStore):
        self._filestore = filestore

    def get_source(self, environment, template):
        if not self._filestore.file_exists(template):
            raise TemplateNotFound(template)
        source = self._filestore.read_text(template)
        return source, template, lambda: True


def _is_component_html(path: str) -> bool:
    lower = path.lower()
    return path.startswith(COMPONENTS_DIR) and (lower.endswith(".html") or lower.endswith(".htm"))


def _is_page_html(path: str) -> bool:
    lower = path.lower()
    return (lower.endswith(".html") or lower.endswith(".htm")) and not _is_component_html(path)


def build(filestore: FileStore) -> InMemoryFileStore:
    """Render Jinja templates in *filestore* and return a new filestore of pure HTML/CSS/JS.

    Rules:
    - HTML pages (not in components/) → rendered through Jinja
    - Component HTML (components/*.html) → excluded (they exist only to be {% include %}d)
    - Everything else (CSS, JS, images, component CSS/JS, …) → copied as-is
    - Internal meta-files (spec.txt, AGENTS.md) → excluded
    """
    env = Environment(loader=FileStoreLoader(filestore), autoescape=False)
    result = InMemoryFileStore()

    for path in filestore.list_files():
        if path in _META_FILES:
            continue
        if _is_component_html(path):
            continue
        if _is_page_html(path):
            try:
                rendered = env.get_template(path).render()
                result.write_text(path, rendered)
            except Exception as exc:
                raise RuntimeError(f"Template render failed for '{path}': {exc}") from exc
        else:
            result.write_bytes(path, filestore.read_bytes(path))

    return result
