"""FastMCP server exposing the site push/read tools to a local coding agent.

Tools are synchronous: the auth path may block on a browser/loopback round-trip,
which is simplest to express synchronously. There is intentionally **no
``deploy_site`` tool** — going live is a site-UI action.
"""
import base64
import mimetypes
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, model_validator

from mcp_server import config
from mcp_server.auth import load_cached_token, make_token_provider, obtain_token_via_browser
from mcp_server.client import SiteApiError, SiteClient

mcp = FastMCP("breba-site")

# Runtime target set by ``switch_product``; None means "use BREBA_PRODUCT_ID".
# Per-process, so a switch lasts for this server's lifetime — one agent session
# over stdio, every connected agent over --http.
_product_override: str | None = None


def _active_product_id() -> str:
    return config.product_id() if _product_override is None else _product_override


def _adopt_picked_product(picked: str) -> None:
    """Retarget the session when the consent page's picker chose another product.

    The picker stays editable even when a specific product was requested; the
    user's pick is authoritative — the token in hand is scoped to it — so the
    session must follow, or every later call would target the old product,
    cache-miss, and re-open the browser.
    """
    global _product_override
    _product_override = picked


# One SiteClient — and thus one persistent HTTP connection pool — per
# (base_url, product) target; a product switch lazily creates the next one.
_clients: dict[tuple[str, str], SiteClient] = {}

# Latest active revision observed per agent session and target. A push carries
# it as an optimistic-concurrency precondition so an agent cannot silently
# overwrite a browser/chat edit made after its read. Keyed by the MCP session
# — over --http each connected agent has its own — so one agent's fresher read
# cannot re-arm another agent's stale push. Historical reads intentionally do
# not update this value: they are often used as reference material, not as the
# edit base. Entries for closed sessions are a few ints; left to process exit.
_observed_versions: dict[tuple, int] = {}


def _guard_key(ctx: Context | None) -> tuple:
    # Direct calls (tests) pass no ctx; stdio has a single session anyway.
    session = id(ctx.session) if ctx is not None else None
    return session, config.base_url(), _active_product_id()


def _remember_active_version(ctx: Context | None, version: int | None) -> None:
    if version is not None:
        _observed_versions[_guard_key(ctx)] = version


def _client() -> SiteClient:
    base = config.base_url()
    key = (base, _active_product_id())
    if key not in _clients:
        provider = make_token_provider(base, key[1],
                                       on_product_change=_adopt_picked_product)
        _clients[key] = SiteClient(base, provider)
    return _clients[key]


def _check_cap(size: int, what: str) -> None:
    cap = config.max_file_bytes()
    if size > cap:
        raise ValueError(
            f"{what} is {size} bytes; the per-file cap is {cap} bytes "
            "(override with BREBA_MCP_MAX_FILE_BYTES)."
        )


# Non-"text/*" content types that are still safe to hand to the model as text.
_TEXT_CONTENT_TYPES = {
    "application/json", "application/javascript", "application/x-javascript",
    "application/ecmascript", "application/xml",
}


def _is_text_content_type(content_type: str) -> bool:
    if not content_type:
        return True  # unknown: let the UTF-8 decode backstop decide
    ct = content_type.split(";")[0].strip().lower()
    return (ct.startswith("text/") or ct in _TEXT_CONTENT_TYPES
            or ct.endswith("+json") or ct.endswith("+xml"))  # e.g. image/svg+xml


def _fetch_file(client: SiteClient, path: str, version: int | None,
                ctx: Context | None) -> tuple[str, bytes]:
    """Fetch one file's bytes: read, version-guard update, cap backstop.

    The guard updates before the cap backstop below: the active revision was
    observed by the read itself, whether or not the content turns out usable.
    The backstop re-checks the real size because version-0 manifests report
    size 0, which makes the callers' pre-download stat checks vacuous.
    """
    data = client.read_file(path, version)
    if version is None:
        _remember_active_version(ctx, data.get("version"))
    raw = base64.b64decode(data["content_b64"])
    _check_cap(len(raw), f"Site file '{data['path']}'")
    return data["path"], raw


class FileArg(BaseModel):
    path: str
    content: str | None = None  # text files: inline content, base64-encoded on the wire
    local_path: str | None = None  # binary assets: local file whose bytes are read by the server

    @model_validator(mode="after")
    def _exactly_one_source(self):
        if (self.content is None) == (self.local_path is None):
            raise ValueError(
                "Provide exactly one of 'content' (inline text) or "
                "'local_path' (local file to read bytes from)."
            )
        return self


@mcp.tool()
def list_site_versions(ctx: Context = None) -> dict:
    """List all site revision numbers and which one is active.

    Every push creates a new revision; older ones stay readable via the
    ``version`` argument of ``list_site_files``/``read_site_file``. Use this to
    review the site's history — e.g. to combine elements from different
    revisions into a new push, or to understand how a design evolved.
    Returns {"versions", "active"}.
    """
    result = _client().list_versions()
    _remember_active_version(ctx, result.get("active"))
    return result


@mcp.tool()
def list_site_files(version: int | None = None, ctx: Context = None) -> dict:
    """List the file paths of a site revision (the active one by default)."""
    result = _client().list_files(version)
    if version is None:
        _remember_active_version(ctx, result.get("version"))
    return result


@mcp.tool()
def read_site_file(path: str, version: int | None = None, ctx: Context = None) -> dict:
    """Read one site file, from the active revision or an older one.

    Pass ``version`` (see ``list_site_versions``) to read a past revision —
    e.g. to pull the background styling from version 5 and the artwork from
    version 9 into a new push. Returns {"path", "content"} with decoded text.

    Text files only: reading a binary file (image, font) fails with a pointer to
    ``download_site_file``, which saves the bytes to a local path instead.
    """
    client = _client()
    # Metadata first: refuse known-binary or oversized files before paying for
    # (and then discarding) the whole download.
    info = client.stat_file(path, version)
    if not _is_text_content_type(info.get("content_type", "")):
        raise ValueError(
            f"'{path}' is a binary file ({info['content_type']}, {info['size']} bytes); "
            "use download_site_file to save it to a local path instead."
        )
    _check_cap(info.get("size", 0), f"Site file '{path}'")
    server_path, raw = _fetch_file(client, path, version, ctx)
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        # Backstop for unknown/lying content types.
        raise ValueError(
            f"'{server_path}' is a binary file ({len(raw)} bytes); "
            "use download_site_file to save it to a local path instead."
        ) from exc
    return {"path": server_path, "content": content}


@mcp.tool()
def download_site_file(path: str, dest_path: str, version: int | None = None,
                       ctx: Context = None) -> dict:
    """Download one site file (binary-safe) to a local path.

    Use this for images, fonts, and other binary assets that ``read_site_file``
    refuses: the bytes go straight from the site to ``dest_path`` on disk without
    entering the conversation. Parent directories are created as needed. Pass
    ``version`` to download from a past revision.
    Returns {"path", "dest_path", "size"}.
    """
    client = _client()
    # Refuse on the manifest size before downloading; _fetch_file keeps the
    # post-download backstop. Its guard update matters here too: a binary asset
    # read from the active revision is an edit base like any text read, and
    # without it a download-only session would push unguarded.
    _check_cap(client.stat_file(path, version).get("size", 0), f"Site file '{path}'")
    server_path, raw = _fetch_file(client, path, version, ctx)
    dest = Path(dest_path).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return {"path": server_path, "dest_path": str(dest), "size": len(raw)}


@mcp.tool()
def push_site(files: list[FileArg], ctx: Context = None) -> dict:
    """Write/overwrite the given files as a new site revision and rebuild the preview.

    Batch every file of one logical change into a SINGLE call — never call this
    once per file. Each call creates a user-visible revision and republishes the
    preview, so a split push shows visitors intermediate, possibly broken states.
    Unpushed files are preserved, never deleted, so a push only needs the files
    the change touches. This does NOT deploy/go-live.
    After an active-revision read, Breba rejects the push if another edit has
    created a newer revision; re-read and reapply the change, then retry.
    Returns {"version", "product_id"}.

    Each file gives its content one of two ways:
    - ``content`` — inline text (HTML/CSS/JS/SVG/…).
    - ``local_path`` — a local file whose bytes the server reads from disk.
      Pass an absolute path: the server's working directory is not the agent's.
      Use this for binary assets (images, fonts): never paste binary or base64
      data into ``content``.

    Maintain the project notes: read ``AGENTS.md`` before working (a new site
    may not have one yet — create it with your first push), and after
    meaningful changes include an updated ``AGENTS.md`` recording the decisions
    and constraints behind them — the site's chat agent reads and extends the
    same file, so this keeps the two in sync.
    """
    payload = []
    for f in files:
        content_type = None
        if f.content is not None:
            raw = f.content.encode()
            # Inline content is text by definition. Without an explicit type,
            # the server guesses from the extension and stamps extensionless
            # files (CNAME, LICENSE) application/octet-stream — read_site_file
            # would then refuse to read back a file this tool pushed as text.
            content_type = mimetypes.guess_type(f.path)[0] or "text/plain"
        else:
            p = Path(f.local_path).expanduser()
            if not p.is_file():
                raise ValueError(f"Local file not found: {f.local_path}")
            # stat before read: never load an oversized file into memory
            _check_cap(p.stat().st_size, f.local_path)
            raw = p.read_bytes()
        _check_cap(len(raw), f"'{f.path}'")
        entry = {"path": f.path, "content_b64": base64.b64encode(raw).decode()}
        if content_type is not None:
            entry["content_type"] = content_type
        payload.append(entry)
    # First-use auth (and any consent-picker product switch it triggers) must
    # complete before the guard is read, or the push would carry a revision
    # observed on the product the session just switched away from. A token
    # expiring between here and the request can still reopen that window, but
    # for seconds rather than for the whole first-auth browser flow.
    _client().ensure_auth()
    key = _guard_key(ctx)  # after auth: the switch, if any, has happened
    expected_version = _observed_versions.get(key)
    try:
        # SiteClient.push omits the field when expected_version is None, so the
        # unguarded payload stays byte-identical to the pre-guard wire format.
        result = _client().push(payload, expected_version=expected_version)
    except SiteApiError as e:
        # A non-409 failure may still have saved a new revision (the router
        # 500s when the preview rebuild fails *after* the save advanced the
        # active pointer). The remembered version is then stale and would
        # deterministically 409 the follow-up push the error asks for, so
        # forget it — the next push runs unguarded, as before any read.
        # A 409 keeps the guard: its re-read/reapply recovery refreshes it.
        if e.status_code != 409:
            _observed_versions.pop(key, None)
        raise
    _remember_active_version(ctx, result.get("version"))
    return result


@mcp.tool()
def get_preview_url() -> dict:
    """Return the preview URL for the current site revision."""
    return _client().preview()


@mcp.tool()
def list_products() -> dict:
    """List the user's products (their websites) and which one this session targets.

    Use this when the user names a product/project/site: find its ``id`` here,
    then pass it to ``switch_product``. Returns
    {"products": [{"id", "name"}, ...], "current": <product_id>}.
    """
    return _client().products()


@mcp.tool()
def switch_product(product_id: str = "") -> dict:
    """Switch this session to another product (website); every site tool then targets it.

    Two modes:
    - ``product_id`` given — switch directly (map a product *name* to its id via
      ``list_products`` first). A previously authorized product switches without
      a browser round-trip; otherwise the browser opens pre-selected for consent.
    - ``product_id`` empty — always opens the browser so the user picks the
      product there. Use this when the user wants to choose interactively.

    The switch lasts for this server process only; it does not change the
    ``BREBA_PRODUCT_ID`` in the agent's MCP config.
    Returns {"product_id", "name"} of the new target.
    """
    global _product_override
    if config.env_token():
        raise ValueError(
            "BREBA_MCP_TOKEN is set, which pins both the token and its product; "
            "unset it (or supply a token for the other product) to switch."
        )
    base = config.base_url()
    if product_id and load_cached_token(base, product_id):
        # Previously authorized: switch silently, no browser round-trip.
        _product_override = product_id
    else:
        # The browser flow's consent picker stays editable even when a specific
        # product was requested, so the user's pick — which the token in hand
        # is scoped to — wins over the requested id. The override commits only
        # once a token is actually in hand: a failed flow raises above this.
        _product_override = obtain_token_via_browser(base, product_id)["product_id"]

    info = _client().products()  # proves the token works and resolves the display name
    current = info["current"]
    name = next((p["name"] for p in info["products"] if p["id"] == current), current)
    return {"product_id": current, "name": name}
