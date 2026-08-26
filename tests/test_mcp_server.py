import base64
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from breba_app.mcp_api.auth import make_code_challenge
from mcp_server import auth, config, server
from mcp_server import client as client_module
from mcp_server.client import SiteClient

BASE = "http://localhost:8080"
PID = "prod-1"


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Point the token cache at a temp dir and clear env overrides per test."""
    monkeypatch.setenv("BREBA_MCP_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("BREBA_MCP_TOKEN", raising=False)
    monkeypatch.delenv("BREBA_BASE_URL", raising=False)
    monkeypatch.delenv("BREBA_PRODUCT_ID", raising=False)
    monkeypatch.delenv("BREBA_MCP_MAX_FILE_BYTES", raising=False)
    monkeypatch.setattr(server, "_product_override", None)
    monkeypatch.setattr(server, "_clients", {})
    monkeypatch.setattr(server, "_observed_versions", {})


# --- token cache -------------------------------------------------------------

def test_expired_cached_token_is_ignored():
    auth.save_token(BASE, PID, "tok-old", expires_at=time.time() + 5)  # within skew
    assert auth.load_cached_token(BASE, PID) is None


def test_cache_is_keyed_by_base_and_product():
    auth.save_token(BASE, PID, "tok-1", expires_at=time.time() + 3600)
    assert auth.load_cached_token(BASE, "other-product") is None
    assert auth.load_cached_token("http://other", PID) is None


def test_save_token_preserves_other_entries():
    auth.save_token(BASE, "prod-a", "tok-a", expires_at=time.time() + 3600)
    auth.save_token(BASE, "prod-b", "tok-b", expires_at=time.time() + 3600)
    assert auth.load_cached_token(BASE, "prod-a") == "tok-a"
    assert auth.load_cached_token(BASE, "prod-b") == "tok-b"


def test_token_cache_file_is_private_and_no_temp_left_behind():
    import stat

    auth.save_token(BASE, PID, "tok-abc", expires_at=time.time() + 3600)

    path = config.token_file()
    # Bearer tokens: owner read/write only, like other CLI credential files.
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # The atomic-replace temp file must not linger next to the cache.
    assert [p.name for p in path.parent.iterdir()] == [path.name]


# --- token provider precedence ----------------------------------------------

def test_provider_prefers_env_token(monkeypatch):
    monkeypatch.setenv("BREBA_MCP_TOKEN", "env-token")
    # Even with a cached token present, env wins and no browser flow runs.
    auth.save_token(BASE, PID, "cached", expires_at=time.time() + 3600)
    monkeypatch.setattr(auth, "obtain_token_via_browser",
                        lambda *a: pytest.fail("should not open browser"))
    provider = auth.make_token_provider(BASE, PID)
    assert provider(False) == "env-token"
    assert provider(True) == "env-token"


def test_provider_uses_cache_then_browser(monkeypatch):
    calls = []
    monkeypatch.setattr(
        auth, "obtain_token_via_browser",
        lambda base, pid: calls.append((base, pid)) or
        {"token": "fresh-token", "product_id": pid, "expires_at": time.time() + 3600},
    )
    provider = auth.make_token_provider(BASE, PID)

    # No cache yet -> browser flow.
    assert provider(False) == "fresh-token"
    assert calls == [(BASE, PID)]

    # Now a valid cache exists -> no browser.
    auth.save_token(BASE, PID, "cached-token", expires_at=time.time() + 3600)
    assert provider(False) == "cached-token"
    assert len(calls) == 1

    # force_refresh bypasses the cache.
    assert provider(True) == "fresh-token"
    assert len(calls) == 2


def test_provider_reports_picked_product_to_callback(monkeypatch):
    # The consent page let the user approve prod-b although prod-a was
    # requested: the provider must surface the pick so the caller retargets.
    monkeypatch.setattr(
        auth, "obtain_token_via_browser",
        lambda base, pid: {"token": "tok-b", "product_id": "prod-b",
                           "expires_at": time.time() + 3600},
    )
    picks = []
    provider = auth.make_token_provider(BASE, "prod-a", on_product_change=picks.append)
    assert provider(False) == "tok-b"
    assert picks == ["prod-b"]


def test_provider_skips_callback_when_pick_matches_request(monkeypatch):
    monkeypatch.setattr(
        auth, "obtain_token_via_browser",
        lambda base, pid: {"token": "tok-a", "product_id": "prod-a",
                           "expires_at": time.time() + 3600},
    )
    picks = []
    provider = auth.make_token_provider(BASE, "prod-a", on_product_change=picks.append)
    assert provider(False) == "tok-a"
    assert picks == []


# --- browser flow: never hangs -----------------------------------------------

def test_browser_flow_times_out_instead_of_hanging(monkeypatch):
    # If the browser never redirects back (e.g. server rendered an error page),
    # the flow must give up with a clear error, not block the tool call forever.
    monkeypatch.setattr(auth.webbrowser, "open", lambda url: True)
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="timed out"):
        auth.obtain_token_via_browser(BASE, PID, timeout=0.3)
    assert time.monotonic() - start < 5


def test_browser_flow_fails_fast_when_no_browser_opens(monkeypatch):
    # On a browserless machine webbrowser.open returns False; the flow must
    # raise immediately with guidance instead of waiting out the full timeout.
    monkeypatch.setattr(auth.webbrowser, "open", lambda url: False)
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="BREBA_MCP_TOKEN"):
        auth.obtain_token_via_browser(BASE, PID, timeout=30)
    assert time.monotonic() - start < 5


def test_browser_flow_surfaces_error_redirect(monkeypatch):
    # The server redirects errors (wrong product ID etc.) back to the loopback
    # callback; the flow must raise them as a descriptive RuntimeError.
    def fake_open(url):
        q = parse_qs(urlparse(url).query)
        redirect_uri, state = q["redirect_uri"][0], q["state"][0]

        def hit_callback():
            httpx.get(redirect_uri, params={
                "error": "invalid_product",
                "error_description": "Product 'nope' does not exist or is not yours.",
                "state": state,
            })

        threading.Thread(target=hit_callback, daemon=True).start()
        return True

    monkeypatch.setattr(auth.webbrowser, "open", fake_open)
    with pytest.raises(RuntimeError, match="invalid_product.*does not exist"):
        auth.obtain_token_via_browser(BASE, PID, timeout=10)


def test_browser_flow_ignores_stray_callback_probes(monkeypatch, mocker):
    # A stray local GET (security software, extension probe) carrying neither
    # code nor error must not end the wait: the flow keeps listening and the
    # real redirect that follows still completes the authorization.
    def fake_open(url):
        q = parse_qs(urlparse(url).query)
        redirect_uri, state = q["redirect_uri"][0], q["state"][0]

        def probe_then_callback():
            httpx.get(redirect_uri)  # no query params at all
            httpx.get(redirect_uri.replace("/callback", "/favicon.ico"))
            httpx.get(redirect_uri, params={"code": "c1", "state": state})

        threading.Thread(target=probe_then_callback, daemon=True).start()
        return True

    monkeypatch.setattr(auth.webbrowser, "open", fake_open)
    mocker.patch.object(auth.httpx, "post", return_value=_FakeResp(
        200, {"token": "tok-1", "product_id": PID, "expires_at": time.time() + 3600},
    ))

    out = auth.obtain_token_via_browser(BASE, PID, timeout=10)
    assert out["token"] == "tok-1"


def test_browser_flow_rejects_wrong_state_callback(monkeypatch):
    # A callback that does carry a code but the wrong state is a real
    # CSRF signal and must still fail fast.
    def fake_open(url):
        redirect_uri = parse_qs(urlparse(url).query)["redirect_uri"][0]
        threading.Thread(
            target=lambda: httpx.get(redirect_uri,
                                     params={"code": "c1", "state": "attacker-state"}),
            daemon=True,
        ).start()
        return True

    monkeypatch.setattr(auth.webbrowser, "open", fake_open)
    with pytest.raises(RuntimeError, match="State mismatch"):
        auth.obtain_token_via_browser(BASE, PID, timeout=10)


def _fake_browser_pick(monkeypatch, mocker, picked_product_id, token="tok-picked"):
    """Simulate the full success path: callback with a code, then /mcp/token."""
    def fake_open(url):
        q = parse_qs(urlparse(url).query)
        redirect_uri, state = q["redirect_uri"][0], q["state"][0]
        threading.Thread(
            target=lambda: httpx.get(redirect_uri, params={"code": "c1", "state": state}),
            daemon=True,
        ).start()
        return True

    monkeypatch.setattr(auth.webbrowser, "open", fake_open)
    mocker.patch.object(auth.httpx, "post", return_value=_FakeResp(
        200, {"token": token, "product_id": picked_product_id,
              "expires_at": time.time() + 3600},
    ))


def test_browser_flow_returns_picked_product_and_caches_both_keys(monkeypatch, mocker):
    # Requested with an empty product id (pick-in-browser mode): the flow must
    # report which product the user picked and cache the token under both the
    # requested (empty) key and the picked product's key.
    _fake_browser_pick(monkeypatch, mocker, picked_product_id="picked-prod")

    out = auth.obtain_token_via_browser(BASE, "", timeout=10)

    assert out["token"] == "tok-picked"
    assert out["product_id"] == "picked-prod"
    assert auth.load_cached_token(BASE, "") == "tok-picked"
    assert auth.load_cached_token(BASE, "picked-prod") == "tok-picked"


def test_browser_flow_sends_pkce_challenge_matching_its_verifier(monkeypatch, mocker):
    seen = {}

    def fake_open(url):
        q = parse_qs(urlparse(url).query)
        seen["challenge"] = q["code_challenge"][0]
        redirect_uri, state = q["redirect_uri"][0], q["state"][0]
        threading.Thread(
            target=lambda: httpx.get(redirect_uri, params={"code": "c1", "state": state}),
            daemon=True,
        ).start()
        return True

    def fake_post(url, json=None, timeout=None):
        seen["verifier"] = json["code_verifier"]
        return _FakeResp(200, {"token": "t", "product_id": PID,
                               "expires_at": time.time() + 3600})

    monkeypatch.setattr(auth.webbrowser, "open", fake_open)
    mocker.patch.object(auth.httpx, "post", side_effect=fake_post)

    auth.obtain_token_via_browser(BASE, PID, timeout=10)

    # The server-side transform is the expected value: the client's inline
    # S256 (mcp_server stays free of breba_app imports) must match it
    # byte-for-byte or the exchange breaks — divergence fails here, not live.
    assert seen["challenge"] == make_code_challenge(seen["verifier"])


def test_browser_flow_never_caches_picked_token_under_requested_id(monkeypatch, mocker):
    # The user can change the product in the consent page's picker even when the
    # flow requested a specific one. The returned token is scoped to the picked
    # product, so caching it under the requested id would make every later
    # lookup "for prod-a" silently push to prod-b.
    _fake_browser_pick(monkeypatch, mocker, picked_product_id="prod-b", token="tok-b")

    out = auth.obtain_token_via_browser(BASE, "prod-a", timeout=10)

    assert out["product_id"] == "prod-b"
    assert auth.load_cached_token(BASE, "prod-b") == "tok-b"
    assert auth.load_cached_token(BASE, "prod-a") is None
    assert auth.load_cached_token(BASE, "") is None  # empty key is pick-in-browser only


# --- HTTP client: 401 -> reauth -> retry ------------------------------------

class _FakeResp:
    def __init__(self, status_code, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(self.text, request=None, response=None)


def _install_fake_http(mocker, fake_request):
    """Replace SiteClient's persistent httpx.Client with a request stub."""
    fake = mocker.Mock()
    fake.request.side_effect = fake_request
    return mocker.patch("mcp_server.client.httpx.Client", return_value=fake), fake


def test_client_retries_once_on_401(mocker):
    provider = lambda force=False: "fresh" if force else "stale"  # noqa: E731

    seen_auth = []

    def fake_request(method, url, headers, **kw):
        seen_auth.append(headers["Authorization"])
        if headers["Authorization"] == "Bearer stale":
            return _FakeResp(401, text="unauthorized")
        return _FakeResp(200, {"files": ["index.html"]})

    _install_fake_http(mocker, fake_request)
    out = SiteClient(BASE, provider).list_files()

    assert out == {"files": ["index.html"]}
    assert seen_auth == ["Bearer stale", "Bearer fresh"]


def test_client_raises_on_4xx(mocker):
    _install_fake_http(mocker, lambda *a, **kw: _FakeResp(404, text="Product not found"))
    with pytest.raises(RuntimeError, match="404"):
        SiteClient(BASE, lambda force=False: "tok").push([])


def test_client_reuses_one_connection_pool(mocker):
    client_cls, fake = _install_fake_http(mocker, lambda *a, **kw: _FakeResp(200, {}))
    c = SiteClient(BASE, lambda force=False: "tok")
    c.list_files()
    c.list_versions()
    c.preview()
    client_cls.assert_called_once_with(base_url=BASE, timeout=60.0)  # one pool
    assert fake.request.call_count == 3


def test_server_caches_one_site_client_per_target(mocker, monkeypatch):
    site_client = mocker.patch("mcp_server.server.SiteClient",
                               side_effect=lambda *a: mocker.Mock())
    first = server._client()
    assert server._client() is first  # same target -> same client, same pool
    assert site_client.call_count == 1

    monkeypatch.setattr(server, "_product_override", "prod-9")
    assert server._client() is not first  # new target -> new client
    assert site_client.call_count == 2


# --- tool encoding/decoding --------------------------------------------------

class _NoAuth:
    """push_site pre-auths before reading the guard; fakes need the hook only."""

    def ensure_auth(self):
        pass


def test_push_site_base64_encodes_content(mocker):
    captured = {}

    class FakeClient(_NoAuth):
        def push(self, files, expected_version=None):
            captured["files"] = files
            return {"version": 8, "product_id": PID}

    mocker.patch("mcp_server.server._client", return_value=FakeClient())
    result = server.push_site([server.FileArg(path="index.html", content="<h1>hi</h1>")])

    assert result == {"version": 8, "product_id": PID}
    sent = captured["files"][0]
    assert sent["path"] == "index.html"
    assert base64.b64decode(sent["content_b64"]).decode() == "<h1>hi</h1>"


def _observing_fake_client(pushes: list, fail_with: int | None = None):
    """FakeClient whose read observes active v6 and whose push records or fails."""

    class FakeClient(_NoAuth):
        def stat_file(self, path, version=None):
            return {"content_type": "text/html", "size": 2}

        def read_file(self, path, version=None):
            return {"path": path, "content_b64": base64.b64encode(b"<p").decode(), "version": 6}

        def push(self, files, expected_version=None):
            pushes.append(expected_version)
            if fail_with is not None:
                raise client_module.SiteApiError(f"POST /mcp/push -> {fail_with}", fail_with)
            return {"version": 7, "product_id": PID}

    return FakeClient()


def test_push_site_uses_the_active_revision_observed_from_a_read(mocker):
    pushes: list = []
    mocker.patch("mcp_server.server._client", return_value=_observing_fake_client(pushes))

    server.read_site_file("index.html")
    server.push_site([server.FileArg(path="index.html", content="<h1>updated</h1>")])

    assert pushes == [6]


def test_push_site_forgets_the_guard_when_a_push_fails_after_possibly_saving(mocker):
    pushes: list = []
    mocker.patch("mcp_server.server._client",
                 return_value=_observing_fake_client(pushes, fail_with=500))

    server.read_site_file("index.html")
    with pytest.raises(client_module.SiteApiError):
        server.push_site([server.FileArg(path="index.html", content="<h1>fix</h1>")])
    # The 500 may have saved a revision; the follow-up push must not carry the
    # now-stale precondition, or it would 409 against the agent's own save.
    with pytest.raises(client_module.SiteApiError):
        server.push_site([server.FileArg(path="index.html", content="<h1>fix</h1>")])

    assert pushes == [6, None]


def test_push_site_keeps_the_guard_across_a_conflict(mocker):
    pushes: list = []
    mocker.patch("mcp_server.server._client",
                 return_value=_observing_fake_client(pushes, fail_with=409))

    server.read_site_file("index.html")
    with pytest.raises(client_module.SiteApiError):
        server.push_site([server.FileArg(path="index.html", content="<h1>fix</h1>")])
    with pytest.raises(client_module.SiteApiError):
        server.push_site([server.FileArg(path="index.html", content="<h1>fix</h1>")])

    # A 409 means the guard did its job; only a re-read may refresh it.
    assert pushes == [6, 6]


def test_observed_versions_are_per_mcp_session(mocker):
    pushes: list = []
    mocker.patch("mcp_server.server._client",
                 return_value=_observing_fake_client(pushes))

    session_a = SimpleNamespace(session=object())
    session_b = SimpleNamespace(session=object())
    server.read_site_file("index.html", ctx=session_a)

    # B never read the active site; it must not inherit A's guard — and A's
    # guard must survive B's push (which would otherwise re-arm or clear it).
    server.push_site([server.FileArg(path="index.html", content="<h1>b</h1>")], ctx=session_b)
    server.push_site([server.FileArg(path="index.html", content="<h1>a</h1>")], ctx=session_a)

    assert pushes == [None, 6]


def test_ctx_is_injected_not_exposed_in_tool_schemas():
    for name in ("list_site_versions", "list_site_files", "read_site_file",
                 "download_site_file", "push_site"):
        tool = server.mcp._tool_manager.get_tool(name)
        assert tool.context_kwarg == "ctx"
        assert "ctx" not in tool.parameters.get("properties", {})


def test_push_site_reads_the_guard_after_auth_retargets_the_session(mocker):
    # The consent picker may switch the session to another product during the
    # push's own first-use auth; the guard must then be the new product's (none
    # here), not the revision observed on the product just switched away from.
    pushes: list = []
    fake = _observing_fake_client(pushes)
    fake.ensure_auth = lambda: server._adopt_picked_product("other-prod")
    mocker.patch("mcp_server.server._client", return_value=fake)

    server.read_site_file("index.html")  # observes v6 on the original product
    server.push_site([server.FileArg(path="index.html", content="<h1>x</h1>")])

    assert pushes == [None]


def test_push_site_uses_the_active_revision_observed_from_a_download(mocker, tmp_path):
    captured = {}

    class FakeClient(_NoAuth):
        def stat_file(self, path, version=None):
            return {"content_type": "image/png", "size": 4}

        def read_file(self, path, version=None):
            return {"path": path, "content_b64": base64.b64encode(b"\x89PNG").decode(), "version": 6}

        def push(self, files, expected_version=None):
            captured["expected_version"] = expected_version
            return {"version": 7, "product_id": PID}

    mocker.patch("mcp_server.server._client", return_value=FakeClient())

    server.download_site_file("logo.png", str(tmp_path / "logo.png"))
    server.push_site([server.FileArg(path="logo.png", local_path=str(tmp_path / "logo.png"))])

    assert captured["expected_version"] == 6


def test_push_site_without_an_active_read_keeps_backward_compatible_payload(mocker):
    captured = {}

    class FakeClient(_NoAuth):
        def push(self, files, expected_version=None):
            captured["files"] = files
            captured["expected_version"] = expected_version
            return {"version": 7, "product_id": PID}

    mocker.patch("mcp_server.server._client", return_value=FakeClient())

    server.push_site([server.FileArg(path="index.html", content="<h1>updated</h1>")])

    assert captured["files"][0]["path"] == "index.html"
    # No read happened, so no precondition may reach the wire (SiteClient drops
    # a None expected_version from the request body).
    assert captured["expected_version"] is None


class _FakeReadClient:
    """read/stat client stub; records calls so tests can assert what was skipped."""

    def __init__(self, content: bytes, content_type: str = "", size: int | None = None):
        self._content = content
        self._stat = {"content_type": content_type,
                      "size": len(content) if size is None else size}
        self.read_calls = []
        self.stat_calls = []

    def stat_file(self, path, version=None):
        self.stat_calls.append((path, version))
        return dict(self._stat)

    def read_file(self, path, version=None):
        self.read_calls.append((path, version))
        return {"path": path, "content_b64": base64.b64encode(self._content).decode()}


def test_read_site_file_decodes_content(mocker):
    fake = _FakeReadClient(b"body{}", content_type="text/css")
    mocker.patch("mcp_server.server._client", return_value=fake)
    assert server.read_site_file("styles.css") == {"path": "styles.css", "content": "body{}"}


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\xffbinary-ish\x80" * 4


def _fake_push_client(mocker, captured):
    class FakeClient(_NoAuth):
        def push(self, files, expected_version=None):
            captured["files"] = files
            return {"version": 9, "product_id": PID}

    mocker.patch("mcp_server.server._client", return_value=FakeClient())


def test_push_site_local_path_sends_file_bytes(mocker, tmp_path):
    asset = tmp_path / "logo.png"
    asset.write_bytes(PNG_BYTES)
    captured = {}
    _fake_push_client(mocker, captured)

    server.push_site([server.FileArg(path="assets/logo.png", local_path=str(asset))])

    sent = captured["files"][0]
    assert sent["path"] == "assets/logo.png"
    assert base64.b64decode(sent["content_b64"]) == PNG_BYTES
    # Bytes from disk may be anything; let the server guess from the extension.
    assert "content_type" not in sent


def test_push_site_sends_text_content_type_for_inline_content(mocker):
    # Inline content is text by definition. Without an explicit type the server
    # stamps extensionless files (CNAME, LICENSE) application/octet-stream, and
    # read_site_file then refuses to read back a file this tool itself pushed.
    captured = {}
    _fake_push_client(mocker, captured)

    server.push_site([server.FileArg(path="CNAME", content="breba.example.com"),
                      server.FileArg(path="index.html", content="<h1>hi</h1>")])

    types = {f["path"]: f["content_type"] for f in captured["files"]}
    assert types == {"CNAME": "text/plain",       # extension-less: text fallback
                     "index.html": "text/html"}   # known extension: real type


def test_file_arg_requires_exactly_one_source(tmp_path):
    with pytest.raises(ValueError, match="exactly one"):
        server.FileArg(path="index.html")
    with pytest.raises(ValueError, match="exactly one"):
        server.FileArg(path="index.html", content="<h1/>", local_path=str(tmp_path / "x"))


def test_push_site_rejects_missing_local_file(mocker, tmp_path):
    _fake_push_client(mocker, {})
    arg = server.FileArg(path="a.png", local_path=str(tmp_path / "nope.png"))
    with pytest.raises(ValueError, match="not found"):
        server.push_site([arg])


def test_push_site_enforces_size_cap(mocker, tmp_path, monkeypatch):
    monkeypatch.setenv("BREBA_MCP_MAX_FILE_BYTES", "10")
    _fake_push_client(mocker, {})

    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 11)
    with pytest.raises(ValueError, match="cap is 10 bytes"):
        server.push_site([server.FileArg(path="big.bin", local_path=str(big))])

    with pytest.raises(ValueError, match="cap is 10 bytes"):
        server.push_site([server.FileArg(path="a.html", content="y" * 11)])


def test_read_site_file_refuses_binary_before_downloading(mocker):
    fake = _FakeReadClient(PNG_BYTES, content_type="image/png")
    mocker.patch("mcp_server.server._client", return_value=fake)
    with pytest.raises(ValueError, match="binary file.*download_site_file"):
        server.read_site_file("logo.png")
    assert fake.read_calls == []  # refused on the stat, no bytes fetched


def test_read_site_file_decode_backstop_for_unknown_content_type(mocker):
    # A missing/unknown content type passes the stat check; the UTF-8 decode
    # backstop must still refuse actual binary bytes.
    fake = _FakeReadClient(PNG_BYTES, content_type="")
    mocker.patch("mcp_server.server._client", return_value=fake)
    with pytest.raises(ValueError, match="binary file.*download_site_file"):
        server.read_site_file("mystery.bin")
    assert len(fake.read_calls) == 1


def test_read_site_file_refuses_oversized_before_downloading(mocker, monkeypatch):
    monkeypatch.setenv("BREBA_MCP_MAX_FILE_BYTES", "10")
    fake = _FakeReadClient(b"x" * 11, content_type="text/html")
    mocker.patch("mcp_server.server._client", return_value=fake)
    with pytest.raises(ValueError, match="cap is 10 bytes"):
        server.read_site_file("huge.html")
    assert fake.read_calls == []


def test_read_site_file_cap_backstop_when_manifest_size_is_zero(mocker, monkeypatch):
    # Version-0 manifests carry placeholder size 0; the post-download check
    # must still keep an oversized file out of the conversation.
    monkeypatch.setenv("BREBA_MCP_MAX_FILE_BYTES", "10")
    fake = _FakeReadClient(b"x" * 11, content_type="text/html", size=0)
    mocker.patch("mcp_server.server._client", return_value=fake)
    with pytest.raises(ValueError, match="cap is 10 bytes"):
        server.read_site_file("huge.html")


def test_download_site_file_writes_bytes(mocker, tmp_path):
    fake = _FakeReadClient(PNG_BYTES, content_type="image/png")
    mocker.patch("mcp_server.server._client", return_value=fake)
    dest = tmp_path / "nested" / "dir" / "logo.png"  # parents created as needed
    result = server.download_site_file("assets/logo.png", str(dest), version=5)

    assert dest.read_bytes() == PNG_BYTES
    assert result == {"path": "assets/logo.png", "dest_path": str(dest), "size": len(PNG_BYTES)}
    assert fake.read_calls == [("assets/logo.png", 5)]


def test_download_site_file_enforces_size_cap_before_downloading(mocker, tmp_path, monkeypatch):
    monkeypatch.setenv("BREBA_MCP_MAX_FILE_BYTES", "4")
    fake = _FakeReadClient(PNG_BYTES, content_type="image/png")
    mocker.patch("mcp_server.server._client", return_value=fake)
    dest = tmp_path / "logo.png"
    with pytest.raises(ValueError, match="cap is 4 bytes"):
        server.download_site_file("logo.png", str(dest))
    assert not dest.exists()
    assert fake.read_calls == []  # refused on the manifest size, no download


def test_max_file_bytes_defaults_to_20mb(monkeypatch):
    assert config.max_file_bytes() == 20 * 1024 * 1024
    monkeypatch.setenv("BREBA_MCP_MAX_FILE_BYTES", "1234")
    assert config.max_file_bytes() == 1234
    monkeypatch.setenv("BREBA_MCP_MAX_FILE_BYTES", "")  # blank .env line = unset
    assert config.max_file_bytes() == 20 * 1024 * 1024


def test_read_site_file_passes_version(mocker):
    fake = _FakeReadClient(b"<v5>", content_type="text/html")
    mocker.patch("mcp_server.server._client", return_value=fake)
    assert server.read_site_file("index.html", version=5)["content"] == "<v5>"
    assert fake.read_calls == [("index.html", 5)]
    assert fake.stat_calls == [("index.html", 5)]


def test_client_sends_version_param_only_when_given(mocker):
    seen_params = []

    def fake_request(method, url, headers, **kw):
        seen_params.append(kw.get("params"))
        return _FakeResp(200, {})

    _install_fake_http(mocker, fake_request)
    c = SiteClient(BASE, lambda force=False: "tok")
    c.list_files()
    c.list_files(version=5)
    c.read_file("index.html")
    c.read_file("index.html", version=9)
    c.stat_file("index.html")
    c.stat_file("index.html", version=9)
    c.list_versions()

    assert seen_params == [
        {},
        {"version": 5},
        {"path": "index.html"},
        {"path": "index.html", "version": 9},
        {"path": "index.html"},
        {"path": "index.html", "version": 9},
        None,
    ]


# --- product listing / switching ----------------------------------------------

PRODUCTS_RESPONSE = {
    "products": [{"id": "prod-1", "name": "Boat Site"}, {"id": "prod-2", "name": "Cafe Site"}],
    "current": "prod-2",
}


class _FakeProductsClient:
    def __init__(self, current="prod-2"):
        self.response = dict(PRODUCTS_RESPONSE, current=current)

    def products(self):
        return self.response


def test_list_products_passes_through(mocker):
    mocker.patch("mcp_server.server._client", return_value=_FakeProductsClient())
    assert server.list_products() == dict(PRODUCTS_RESPONSE, current="prod-2")


def test_switch_product_with_cached_token_skips_browser(mocker, monkeypatch):
    # A product that was authorized before switches silently: no browser.
    auth.save_token(BASE, "prod-2", "tok-2", expires_at=time.time() + 3600)
    monkeypatch.setattr(server, "obtain_token_via_browser",
                        lambda *a, **kw: pytest.fail("should not open browser"))
    mocker.patch("mcp_server.server._client", return_value=_FakeProductsClient())

    result = server.switch_product("prod-2")

    assert result == {"product_id": "prod-2", "name": "Cafe Site"}
    assert server._active_product_id() == "prod-2"


def test_switch_product_without_id_forces_browser_pick(mocker):
    # Even with a cached token, an empty product_id must reopen the browser so
    # the user can pick — that IS the switch gesture in pick-in-browser mode.
    auth.save_token(BASE, "", "tok-old", expires_at=time.time() + 3600)
    browser = mocker.patch(
        "mcp_server.server.obtain_token_via_browser",
        return_value={"token": "tok-1", "product_id": "prod-1",
                      "expires_at": time.time() + 3600},
    )
    mocker.patch("mcp_server.server._client", return_value=_FakeProductsClient(current="prod-1"))

    result = server.switch_product()

    browser.assert_called_once_with(BASE, "")
    assert result == {"product_id": "prod-1", "name": "Boat Site"}
    assert server._active_product_id() == "prod-1"


def test_switch_product_adopts_product_picked_in_consent_page(mocker, monkeypatch):
    # No cached token for prod-1 -> browser flow; the user changes the consent
    # page's picker to prod-2 and approves. The pick is authoritative: the
    # session must target prod-2, matching the prod-2-scoped token.
    monkeypatch.setattr(
        server, "obtain_token_via_browser",
        lambda base, pid: {"token": "tok-2", "product_id": "prod-2",
                           "expires_at": time.time() + 3600},
    )
    mocker.patch("mcp_server.server._client",
                 return_value=_FakeProductsClient(current="prod-2"))

    result = server.switch_product("prod-1")

    assert result == {"product_id": "prod-2", "name": "Cafe Site"}
    assert server._active_product_id() == "prod-2"


def test_client_retargets_session_when_user_picks_other_product(mocker, monkeypatch):
    # A tool call targeting prod-a triggers the browser flow; the user picks
    # prod-b there. The session override must follow the pick so later calls
    # use the prod-b token instead of cache-missing on prod-a forever.
    monkeypatch.setenv("BREBA_PRODUCT_ID", "prod-a")
    monkeypatch.setattr(
        auth, "obtain_token_via_browser",
        lambda base, pid: {"token": "tok-b", "product_id": "prod-b",
                           "expires_at": time.time() + 3600},
    )
    captured = {}

    def fake_site_client(base, provider):
        captured.setdefault("providers", []).append(provider)
        return mocker.Mock()

    mocker.patch("mcp_server.server.SiteClient", side_effect=fake_site_client)

    server._client()
    assert captured["providers"][0](False) == "tok-b"  # browser flow, user picked prod-b
    assert server._active_product_id() == "prod-b"


def test_switch_product_failed_browser_keeps_old_target(mocker, monkeypatch):
    monkeypatch.setenv("BREBA_PRODUCT_ID", "prod-2")
    monkeypatch.setattr(
        server, "obtain_token_via_browser",
        mocker.Mock(side_effect=RuntimeError("Authorization failed (access_denied)")),
    )
    with pytest.raises(RuntimeError, match="access_denied"):
        server.switch_product("prod-1")
    assert server._active_product_id() == "prod-2"  # override not committed


def test_switch_product_rejected_when_env_token_pins_product(monkeypatch):
    monkeypatch.setenv("BREBA_MCP_TOKEN", "pinned-token")
    with pytest.raises(ValueError, match="BREBA_MCP_TOKEN"):
        server.switch_product("prod-1")


# --- listing tools: pass-through and guard arming ------------------------------

def _listing_fake_client(pushes: list):
    """Fake whose listings report active revision 2 and whose push records the guard."""

    class FakeClient(_NoAuth):
        def list_versions(self):
            return {"versions": [0, 1, 2], "active": 2}

        def list_files(self, version=None):
            v = 2 if version is None else version
            return {"files": ["index.html"], "version": v}

        def preview(self):
            return {"preview_url": "http://prod-1.localhost:8088/index.html"}

        def push(self, files, expected_version=None):
            pushes.append(expected_version)
            return {"version": 3, "product_id": PID}

    return FakeClient()


def test_list_site_versions_passes_through_and_arms_the_guard(mocker):
    # The active revision is observed by any active-state read, not just
    # read_site_file: a session that only listed versions must still push guarded.
    pushes: list = []
    mocker.patch("mcp_server.server._client", return_value=_listing_fake_client(pushes))

    assert server.list_site_versions() == {"versions": [0, 1, 2], "active": 2}
    server.push_site([server.FileArg(path="index.html", content="<h1>x</h1>")])

    assert pushes == [2]


def test_list_site_files_arms_the_guard_only_for_the_active_listing(mocker):
    pushes: list = []
    mocker.patch("mcp_server.server._client", return_value=_listing_fake_client(pushes))

    # A historical listing is reference material, not an edit base: no guard.
    assert server.list_site_files(version=1) == {"files": ["index.html"], "version": 1}
    server.push_site([server.FileArg(path="index.html", content="<h1>x</h1>")])

    # An active listing observes the current revision and arms the guard.
    assert server.list_site_files() == {"files": ["index.html"], "version": 2}
    server.push_site([server.FileArg(path="index.html", content="<h1>y</h1>")])

    assert pushes == [None, 2]


def test_get_preview_url_passes_through(mocker):
    mocker.patch("mcp_server.server._client", return_value=_listing_fake_client([]))
    assert server.get_preview_url() == {
        "preview_url": "http://prod-1.localhost:8088/index.html"}


# --- token cache: atomic-write failure path ------------------------------------

def test_failed_cache_write_leaves_no_temp_and_keeps_the_old_cache(mocker):
    auth.save_token(BASE, PID, "tok-1", expires_at=time.time() + 3600)

    mocker.patch("mcp_server.auth.json.dumps", side_effect=TypeError("boom"))
    with pytest.raises(TypeError):
        auth.save_token(BASE, PID, "tok-2", expires_at=time.time() + 3600)
    mocker.stopall()

    # The failed write's temp file is cleaned up and the old cache survives.
    path = config.token_file()
    assert [p.name for p in path.parent.iterdir()] == [path.name]
    assert auth.load_cached_token(BASE, PID) == "tok-1"


# --- __main__: transport selection ----------------------------------------------

def test_main_defaults_to_stdio(mocker, monkeypatch):
    import mcp_server.__main__ as entry

    run = mocker.patch.object(entry.mcp, "run")
    monkeypatch.setattr("sys.argv", ["mcp_server"])
    entry.main()
    run.assert_called_once_with(transport="stdio")


def test_main_http_flag_selects_streamable_http_and_binds(mocker, monkeypatch):
    import mcp_server.__main__ as entry

    run = mocker.patch.object(entry.mcp, "run")
    # mcp.settings is module-global state; restore it so later tests (or a
    # stdio run in the same process) don't inherit this test's bind address.
    monkeypatch.setattr(entry.mcp, "settings", mocker.Mock(wraps=entry.mcp.settings))
    monkeypatch.setattr("sys.argv", ["mcp_server", "--http", "--host", "0.0.0.0", "--port", "9009"])

    entry.main()

    run.assert_called_once_with(transport="streamable-http")
    assert entry.mcp.settings.host == "0.0.0.0"
    assert entry.mcp.settings.port == 9009
