import logging
import re
from datetime import timezone, datetime
from html.parser import HTMLParser

from breba_app.filesystem import FileStore
from breba_app.paths import templates
from breba_app.storage import PreviewFileStore

logger = logging.getLogger(__name__)


class CanonicalParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.canonical_url = None

    def handle_starttag(self, tag, attrs):
        # Look for <link> tags
        if tag == 'link':
            attrs_dict = dict(attrs)
            # Check if it's a canonical link
            if attrs_dict.get('rel') == 'canonical':
                self.canonical_url = attrs_dict.get('href')


def get_canonical_url(html: str) -> str:
    parser = CanonicalParser()
    parser.feed(html)
    return parser.canonical_url


def generate_sitemap_xml(urls: list[dict]):
    time_now = datetime.now(timezone.utc).date().isoformat()
    sitemap_template = templates.get_template("sitemap.xml")
    return sitemap_template.render(urls=urls, now=time_now)


def generate_robots_txt(canonical_url: str):
    canonical_url = canonical_url.rstrip("/")
    return f"""User-agent: *
Allow: /

Sitemap: {canonical_url}/sitemap.xml"""


_SCRIPT_TAG = (
    '<script src="https://cdn.breba.app/breba/preview_bridge.js"></script>'
)

# Case-insensitive patterns. We keep them simple but robust enough for typical HTML.
_BODY_OPEN_RE = re.compile(r"<body\b[^>]*>", re.IGNORECASE)
_BODY_CLOSE_RE = re.compile(r"</body\s*>", re.IGNORECASE)


def _inject_preview_bridge(html: str) -> str:
    """
    Returns modified HTML if injection happened, else None (no <body> found).
    """
    m_open = _BODY_OPEN_RE.search(html)
    if not m_open:
        return html

    m_close = _BODY_CLOSE_RE.search(html)
    if m_close:
        # Insert right before </body>
        insert_at = m_close.start()
        return html[:insert_at] + _SCRIPT_TAG + "\n" + html[insert_at:]

    return html


async def build_preview(product_id: str, filestore: FileStore) -> None:
    """
    Copies ALL files to the preview bucket prefix {product_id}/.
    Injects preview bridge into any HTML file that contains a <body> tag.
    """
    target_filestore = PreviewFileStore(product_id=product_id)
    failed = []
    for path in filestore.list_files():
        try:
            lower = path.lower()
            if lower.endswith(".html") or lower.endswith(".htm"):
                file_text = filestore.read_text(path)
                modified_html = _inject_preview_bridge(file_text)
                target_filestore.write_text(path, modified_html)
            else:
                target_filestore.write_bytes(path, filestore.read_bytes(path))
        except Exception:
            logger.exception("Failed to copy %r to preview; skipping", path)
            failed.append(path)

    await target_filestore.flush()

    if failed:
        raise RuntimeError(f"Preview build failed for {len(failed)} file(s): {', '.join(failed)}")

if __name__ == "__main__":
    urls_list = [
        {
            'loc': 'https://example.com/'
        },
        {
            'loc': 'https://example.com/about'
        },
        {
            'loc': 'https://example.com/contact'
        }
    ]
    print(generate_sitemap_xml(urls_list))
    print(generate_robots_txt("https://example.com/"))
