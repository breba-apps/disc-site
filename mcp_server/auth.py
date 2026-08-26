"""Token acquisition for the local MCP server.

Order of precedence when a tool needs a bearer token:
  1. ``BREBA_MCP_TOKEN`` env var (headless/CI) — used verbatim, never refreshed.
  2. A non-expired token cached at ``~/.config/breba-mcp/token.json``.
  3. The interactive loopback browser flow against the product's SSO-gated
     ``/mcp/authorize`` → single-use ``code`` → ``POST /mcp/token`` → bearer.

A ``token_provider`` is a callable ``(force_refresh: bool) -> str``. The HTTP
client calls it with ``force_refresh=True`` after a ``401`` to re-run the browser
flow and retry once.
"""
import base64
import hashlib
import html
import json
import logging
import os
import secrets
import socketserver
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from mcp_server import config

# Treat a token as expired this many seconds early, to avoid racing the boundary.
_EXPIRY_SKEW = 30

# Give up on the browser flow after this long, so an abandoned tab (or an error
# page that never redirects back) can't hang the agent's tool call forever.
_BROWSER_FLOW_TIMEOUT = 300.0
_POLL_INTERVAL = 1.0

logger = logging.getLogger(__name__)

TokenProvider = Callable[[bool], str]


def _cache_key(base_url: str, product_id: str) -> str:
    return f"{base_url}|{product_id}"


def _read_cache() -> dict:
    try:
        return json.loads(config.token_file().read_text())
    except (json.JSONDecodeError, OSError):  # missing/corrupt file included
        return {}


def _write_cache(data: dict) -> None:
    """Write the token cache privately (0600) and atomically.

    The file holds long-lived bearer tokens, so it must never be world-readable
    (cf. gh/aws/gcloud credential files). Writing to a same-directory temp file
    and ``os.replace``-ing it in means a racing reader never sees a truncated
    file — a torn read would parse as ``{}`` and a subsequent save would then
    wipe every other cached token.
    """
    cfg_dir = config.config_dir()
    cfg_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = config.token_file()
    fd, tmp = tempfile.mkstemp(dir=cfg_dir, prefix=f".{path.name}.")  # 0600 by mkstemp
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data, indent=2))
        os.replace(tmp, path)  # atomic; the file inherits the temp's 0600 mode
    except BaseException:
        os.unlink(tmp)
        raise


def load_cached_token(base_url: str, product_id: str) -> str | None:
    entry = _read_cache().get(_cache_key(base_url, product_id))
    if not entry:
        return None
    if entry.get("expires_at", 0) <= time.time() + _EXPIRY_SKEW:
        return None
    return entry.get("token")


def save_token(base_url: str, product_id: str, token: str, expires_at: float) -> None:
    data = _read_cache()
    data[_cache_key(base_url, product_id)] = {"token": token, "expires_at": expires_at}
    _write_cache(data)


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (stdlib naming)
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        query = parse_qs(parsed.query)
        if "code" not in query and "error" not in query:
            # A stray probe (security software, browser extension, curl) with
            # neither outcome parameter is not the authorize redirect: answer
            # it without recording, so the wait loop keeps listening for the
            # real callback instead of aborting on a spurious state mismatch.
            self.send_response(204)
            self.end_headers()
            return
        self.server.callback_query = query
        if "error" in query:
            detail = query.get("error_description", query["error"])[0]
            message = f"Authorization failed: {html.escape(detail)}"
        else:
            message = "Authorization complete. You can close this window."
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            f"<html><body><p>{message}</p>"
            "<script>window.close()</script></body></html>".encode()
        )

    def log_message(self, *args):  # silence the default stderr logging
        pass


def _await_authorization_code(server: socketserver.TCPServer, auth_url: str,
                              state: str, timeout: float) -> str:
    """Open the browser, wait for the loopback callback, and return the code.

    Validates the callback: an ``error`` redirect or a ``state`` mismatch
    raises, as does hitting ``timeout`` before any callback arrives.
    """
    deadline = time.monotonic() + timeout
    try:
        # The agent driving this stdio server never sees stderr, and the user
        # watching the browser doesn't need the URL — keep it as a log
        # breadcrumb only.
        logger.info("Opening browser to authorize: %s", auth_url)
        if not webbrowser.open(auth_url):
            raise RuntimeError(
                "Could not open a browser for the authorization flow on this "
                "machine. Authorize once on a machine with a browser (run this "
                "MCP server there against the same BREBA_BASE_URL), copy the "
                "token from ~/.config/breba-mcp/token.json, and set it here as "
                "BREBA_MCP_TOKEN."
            )
        while server.callback_query is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"Authorization timed out after {int(timeout)}s waiting for the "
                    "browser callback. Complete the sign-in/consent in the browser "
                    "(and check BREBA_PRODUCT_ID), then retry."
                )
            server.timeout = min(_POLL_INTERVAL, remaining)
            server.handle_request()  # one request at a time; ignores favicon etc.
    finally:
        server.server_close()

    query = server.callback_query
    if "error" in query:
        error = query["error"][0]
        detail = query.get("error_description", [""])[0]
        raise RuntimeError(
            f"Authorization failed ({error})" + (f": {detail}" if detail else "")
        )
    if query.get("state", [None])[0] != state:
        raise RuntimeError("State mismatch in authorization callback (possible CSRF).")
    return query["code"][0]


def obtain_token_via_browser(base_url: str, product_id: str,
                             timeout: float = _BROWSER_FLOW_TIMEOUT) -> dict:
    """Run the loopback browser flow; return {"token", "product_id", "expires_at"}.

    ``product_id`` may be empty — the user then picks the product on the consent
    page, and the returned ``product_id`` is the one actually picked. The token is
    cached under the *picked* product id only: it is scoped to that product, so
    caching it under a differing requested id would make later lookups for the
    requested product silently operate on the picked one. In pick-in-browser mode
    (empty ``product_id``) it is additionally cached under the empty key, so the
    next session without ``BREBA_PRODUCT_ID`` reuses the last pick without a
    browser round-trip.
    """
    server = socketserver.TCPServer(("127.0.0.1", 0), _CallbackHandler)
    server.callback_query = None
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    # 16 bytes = 128 bits, the conventional size for an unguessable CSRF token.
    state = secrets.token_urlsafe(16)
    # PKCE (RFC 7636, S256): the verifier never leaves this process, so a code
    # intercepted between browser and loopback can't be exchanged without it.
    # 48 bytes encode to 64 chars, inside the 43-128 the RFC requires (32 bytes
    # would sit exactly at the 43-char minimum).
    code_verifier = secrets.token_urlsafe(48)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()

    params = {"redirect_uri": redirect_uri, "state": state,
              "code_challenge": code_challenge}
    if product_id:
        params["product_id"] = product_id
    auth_url = f"{base_url}/mcp/authorize?{urlencode(params)}"

    code = _await_authorization_code(server, auth_url, state, timeout)

    resp = httpx.post(f"{base_url}/mcp/token",
                      json={"code": code, "code_verifier": code_verifier}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    picked = data.get("product_id") or product_id
    save_token(base_url, picked, data["token"], data["expires_at"])
    if not product_id and picked:
        # Pick-in-browser mode: also cache under the "no product configured" key.
        save_token(base_url, "", data["token"], data["expires_at"])
    return {"token": data["token"], "product_id": picked, "expires_at": data["expires_at"]}


def make_token_provider(
    base_url: str, product_id: str,
    on_product_change: Callable[[str], None] | None = None,
) -> TokenProvider:
    """Build a TokenProvider for ``product_id`` on ``base_url``.

    The consent page's product picker stays editable even when the flow
    requested a specific product, so the user may approve a *different* one.
    That pick is authoritative: the returned token is scoped to it, and it is
    cached under the picked id only. When that happens, ``on_product_change``
    is called with the picked id so the caller can retarget its session to
    match the token it is about to use.
    """
    def provider(force_refresh: bool = False) -> str:
        token = config.env_token()
        if token:
            return token  # user-supplied; cannot be refreshed
        if not force_refresh:
            cached = load_cached_token(base_url, product_id)
            if cached:
                return cached
        result = obtain_token_via_browser(base_url, product_id)
        if result["product_id"] != product_id and on_product_change is not None:
            on_product_change(result["product_id"])
        return result["token"]

    return provider
