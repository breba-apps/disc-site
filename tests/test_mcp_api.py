import asyncio
import base64
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from breba_app.filesystem.in_memory_store import InMemoryFileStore
from breba_app.filesystem.models import FileWrite
from breba_app.filesystem.versioned_r2 import NotFound
from breba_app.mcp_api import auth
from breba_app.mcp_api import store as store_module
from breba_app.mcp_api.router import router

SECRET = "test-secret"
USER_ID = "user-1"
PRODUCT_ID = "prod-1"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", SECRET)


# --- auth.py: stateless HMAC token signing -----------------------------------

def test_token_roundtrip():
    tok = auth.mint_token(USER_ID, PRODUCT_ID)[0]
    data = auth.verify_token(tok)
    assert data["user_id"] == USER_ID
    assert data["product_id"] == PRODUCT_ID


def test_tampered_token_rejected():
    tok = auth.mint_token(USER_ID, PRODUCT_ID)[0]
    body, sig = tok.split(".", 1)
    tampered = f"{body}.{'0' * len(sig)}"
    assert auth.verify_token(tampered) is None


def test_expired_token_rejected():
    tok = auth.mint_token(USER_ID, PRODUCT_ID, ttl=-10)[0]
    assert auth.verify_token(tok) is None


def test_code_and_token_kinds_dont_cross_validate():
    # A short-lived browser code must not be accepted as a bearer token, and vice versa.
    assert auth.verify_token(auth.mint_code(USER_ID, PRODUCT_ID)) is None
    assert auth.verify_code(auth.mint_token(USER_ID, PRODUCT_ID)[0]) is None


def test_malformed_token_rejected():
    assert auth.verify_token("not-a-token") is None


def test_verify_without_secret_raises_instead_of_401(monkeypatch):
    # A missing CHAINLIT_AUTH_SECRET is misconfiguration and must surface loudly,
    # not masquerade as an invalid token.
    tok = auth.mint_token(USER_ID, PRODUCT_ID)[0]
    monkeypatch.delenv("CHAINLIT_AUTH_SECRET")
    with pytest.raises(RuntimeError, match="CHAINLIT_AUTH_SECRET"):
        auth.verify_token(tok)


# --- router.py: headless push API --------------------------------------------

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def bearer():
    return {"Authorization": f"Bearer {auth.mint_token(USER_ID, PRODUCT_ID)[0]}"}


@pytest.fixture
def existing_store(mocker):
    """Patch storage so the product exists with two files already on it."""
    store = InMemoryFileStore()
    store.write_bytes("index.html", b"<old>")
    store.write_bytes("styles.css", b"body{}")
    product = mocker.patch("breba_app.mcp_api.router.Product")
    product.find_one = mocker.AsyncMock(return_value=object())  # product exists

    # /mcp/files and /mcp/file read via the targeted store helpers, not a full
    # download. The helpers resolve version=None to the active version (0 here)
    # and return it alongside the payload.
    async def _list_files(user_id, product_id, version=None):
        return store.list_files(), 0 if version is None else version

    async def _read_file(user_id, product_id, path, version=None):
        if not store.file_exists(path):
            raise NotFound(f"{path} not found in version {version}")
        return FileWrite(path=path, content=store.read_bytes(path)), 0 if version is None else version

    mocker.patch("breba_app.mcp_api.store.list_files", mocker.AsyncMock(side_effect=_list_files))
    mocker.patch("breba_app.mcp_api.store.read_file", mocker.AsyncMock(side_effect=_read_file))
    mocker.patch("breba_app.mcp_api.store.read_all_files",
                 mocker.AsyncMock(return_value=store))
    mocker.patch("breba_app.mcp_api.router.get_active_version", mocker.AsyncMock(return_value=0))
    save = mocker.patch("breba_app.mcp_api.router.save_files",
                        mocker.AsyncMock(return_value=7))
    mocker.patch("breba_app.mcp_api.router.build_preview_incremental", mocker.AsyncMock())
    mocker.patch("breba_app.mcp_api.router.get_index_html_path",
                 return_value="http://prod-1.localhost:8088/index.html")
    return store, save


def test_unauthenticated_request_is_401_with_pointer(client):
    resp = client.get("/mcp/files")
    assert resp.status_code == 401
    assert "/mcp/authorize" in resp.headers.get("WWW-Authenticate", "")


def test_list_files(client, bearer, existing_store):
    resp = client.get("/mcp/files", headers=bearer)
    assert resp.status_code == 200
    assert resp.json() == {"files": ["index.html", "styles.css"], "version": 0}


def test_read_file(client, bearer, existing_store):
    resp = client.get("/mcp/file", params={"path": "index.html"}, headers=bearer)
    assert resp.status_code == 200
    assert base64.b64decode(resp.json()["content_b64"]) == b"<old>"
    assert resp.json()["version"] == 0


def test_read_missing_file_is_404(client, bearer, existing_store):
    resp = client.get("/mcp/file", params={"path": "nope.html"}, headers=bearer)
    assert resp.status_code == 404
    assert "nope.html" in resp.json()["detail"]


def test_list_versions(client, bearer, mocker):
    mocker.patch("breba_app.mcp_api.router.list_versions",
                 mocker.AsyncMock(return_value=[0, 1, 2, 3]))
    mocker.patch("breba_app.mcp_api.router.get_active_version",
                 mocker.AsyncMock(return_value=3))
    resp = client.get("/mcp/versions", headers=bearer)
    assert resp.status_code == 200
    assert resp.json() == {"versions": [0, 1, 2, 3], "active": 3}


def test_read_file_from_specific_version(client, bearer, mocker):
    read_file = mocker.patch(
        "breba_app.mcp_api.store.read_file",
        mocker.AsyncMock(return_value=(FileWrite(path="index.html", content=b"<v5>"), 5)))
    resp = client.get("/mcp/file", params={"path": "index.html", "version": 5}, headers=bearer)
    assert resp.status_code == 200
    assert base64.b64decode(resp.json()["content_b64"]) == b"<v5>"
    assert resp.json()["version"] == 5
    read_file.assert_awaited_once_with(USER_ID, PRODUCT_ID, "index.html", 5)


def test_nonexistent_version_is_404(client, bearer, mocker):
    mocker.patch("breba_app.mcp_api.store.list_files",
                 mocker.AsyncMock(side_effect=NotFound("Version 99 does not exist")))
    resp = client.get("/mcp/files", params={"version": 99}, headers=bearer)
    assert resp.status_code == 404
    assert "99" in resp.json()["detail"]


def test_missing_active_manifest_404_names_the_resolved_version(client, bearer, mocker):
    # No version param: the store resolves the active pointer to 3, whose
    # manifest is gone; its NotFound names 3, and the 404 must relay that
    # rather than report the never-passed request parameter.
    mocker.patch("breba_app.mcp_api.store.list_files",
                 mocker.AsyncMock(side_effect=NotFound("Version 3 does not exist")))
    resp = client.get("/mcp/files", headers=bearer)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Version 3 does not exist"


def test_push_merges_and_preserves_unpushed_files(client, bearer, existing_store):
    store, save = existing_store
    new_html = base64.b64encode(b"<new>").decode()
    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": "index.html", "content_b64": new_html}]})
    assert resp.status_code == 200
    assert resp.json() == {"version": 7, "product_id": PRODUCT_ID}

    # Merge-only contract: only the pushed file is written; the unpushed file is
    # preserved by the manifest merge in batch_write, not by re-saving the snapshot.
    saved = save.call_args.args[2]
    assert [(fw.path, fw.content) for fw in saved] == [("index.html", b"<new>")]
    # The preview store still holds the full merged state.
    assert store.read_bytes("index.html") == b"<new>"
    assert store.read_bytes("styles.css") == b"body{}"


def test_push_rejects_an_outdated_expected_version(client, bearer, existing_store, mocker):
    _, save = existing_store
    mocker.patch("breba_app.mcp_api.router.get_active_version", mocker.AsyncMock(return_value=4))
    preview = mocker.patch("breba_app.mcp_api.router.build_preview_incremental", mocker.AsyncMock())
    content = base64.b64encode(b"<new>").decode()

    resp = client.post(
        "/mcp/push", headers=bearer,
        json={"files": [{"path": "index.html", "content_b64": content}], "expected_version": 3},
    )

    assert resp.status_code == 409
    assert "changed from revision 3 to 4" in resp.json()["detail"]
    save.assert_not_called()
    preview.assert_not_called()


def test_unguarded_push_skips_the_version_lookup(client, bearer, existing_store, mocker):
    gav = mocker.patch("breba_app.mcp_api.router.get_active_version",
                       mocker.AsyncMock(return_value=4))
    content = base64.b64encode(b"<new>").decode()

    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": "index.html", "content_b64": content}]})

    assert resp.status_code == 200
    gav.assert_not_awaited()


def test_push_accepts_the_current_expected_version(client, bearer, existing_store, mocker):
    _, save = existing_store
    mocker.patch("breba_app.mcp_api.router.get_active_version", mocker.AsyncMock(return_value=4))
    content = base64.b64encode(b"<new>").decode()

    resp = client.post(
        "/mcp/push", headers=bearer,
        json={"files": [{"path": "index.html", "content_b64": content}], "expected_version": 4},
    )

    assert resp.status_code == 200
    save.assert_awaited_once()


@pytest.mark.parametrize("bad_path", ["../evil.html", "a/../evil.html", "bad\x00name.html", "dir/", ""])
def test_push_invalid_path_is_400_with_no_side_effects(client, bearer, existing_store, mocker, bad_path):
    _, save = existing_store
    preview = mocker.patch("breba_app.mcp_api.router.build_preview_incremental", mocker.AsyncMock())
    content = base64.b64encode(b"x").decode()
    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": bad_path, "content_b64": content}]})
    assert resp.status_code == 400
    assert bad_path in resp.json()["detail"]
    save.assert_not_called()
    preview.assert_not_called()


def test_push_uses_sanitized_paths(client, bearer, existing_store):
    _, save = existing_store
    content = base64.b64encode(b"x").decode()
    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": "./css//styles.css", "content_b64": content}]})
    assert resp.status_code == 200
    assert [fw.path for fw in save.call_args.args[2]] == ["css/styles.css"]


def test_push_oversized_file_is_413_with_no_side_effects(client, bearer, existing_store, mocker, monkeypatch):
    _, save = existing_store
    preview = mocker.patch("breba_app.mcp_api.router.build_preview_incremental", mocker.AsyncMock())
    monkeypatch.setenv("MCP_MAX_FILE_BYTES", "10")
    small = base64.b64encode(b"y" * 10).decode()
    big = base64.b64encode(b"x" * 11).decode()
    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": "ok.css", "content_b64": small},
                                       {"path": "big.png", "content_b64": big}]})
    assert resp.status_code == 413
    assert "big.png is 11 bytes" in resp.json()["detail"]
    save.assert_not_called()  # one bad file rejects the whole batch, before any write
    preview.assert_not_called()


def test_push_at_cap_is_accepted(client, bearer, existing_store, monkeypatch):
    monkeypatch.setenv("MCP_MAX_FILE_BYTES", "10")
    content = base64.b64encode(b"y" * 10).decode()
    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": "ok.css", "content_b64": content}]})
    assert resp.status_code == 200


def test_push_blank_tuning_env_vars_fall_back_to_defaults(client, bearer, existing_store, monkeypatch):
    # sample.env-style blank values (VAR=) must count as unset, not crash int("").
    monkeypatch.setenv("MCP_MAX_FILE_BYTES", "")
    content = base64.b64encode(b"x").decode()
    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": "a.css", "content_b64": content}]})
    assert resp.status_code == 200


def test_push_empty_file_list_is_400(client, bearer, existing_store):
    # batch_write rejects an empty batch; fail fast instead of a 500 mid-gather.
    resp = client.post("/mcp/push", headers=bearer, json={"files": []})
    assert resp.status_code == 400


def test_push_overlays_live_session_state(client, bearer, existing_store, mocker):
    # A live chat session's in-memory filestore must receive the pushed files,
    # otherwise the next coder run would persist stale content over the push.
    live_store = InMemoryFileStore()
    live_store.write_bytes("index.html", b"<old>")
    live_store.write_bytes("styles.css", b"body{}")
    mocker.patch("breba_app.mcp_api.router.state_exists", return_value=True)
    state = mocker.Mock(filestore=live_store)
    mocker.patch("breba_app.mcp_api.router.load_state", return_value=state)

    new_html = base64.b64encode(b"<new>").decode()
    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": "index.html", "content_b64": new_html}]})
    assert resp.status_code == 200
    assert live_store.read_bytes("index.html") == b"<new>"
    assert live_store.read_bytes("styles.css") == b"body{}"


def test_push_without_live_session_skips_overlay(client, bearer, existing_store, mocker):
    mocker.patch("breba_app.mcp_api.router.state_exists", return_value=False)
    load_state = mocker.patch("breba_app.mcp_api.router.load_state")
    new_html = base64.b64encode(b"<new>").decode()
    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": "index.html", "content_b64": new_html}]})
    assert resp.status_code == 200
    load_state.assert_not_called()


def test_push_threads_content_type_into_the_saved_files(client, bearer, existing_store):
    # An explicit type must reach batch_write, or extensionless text files
    # (CNAME, LICENSE) get stamped application/octet-stream in the manifest and
    # the MCP read tools permanently refuse them as binary. Files pushed without
    # one must arrive as None so batch_write guesses from the extension.
    _, save = existing_store
    cname = base64.b64encode(b"breba.example.com").decode()
    html = base64.b64encode(b"<h1>hi</h1>").decode()
    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": "CNAME", "content_b64": cname,
                                        "content_type": "text/plain"},
                                       {"path": "index.html", "content_b64": html}]})
    assert resp.status_code == 200
    saved = save.call_args.args[2]
    assert [(fw.path, fw.content_type) for fw in saved] == [
        ("CNAME", "text/plain"), ("index.html", None)]


def test_push_save_failure_skips_preview_build(client, bearer, existing_store, mocker):
    # The preview build publishes to the public bucket; if nothing was durably
    # versioned, nothing may reach it (mirrors POST /upload's save-then-preview
    # ordering — a build started before/alongside the save would trip this too).
    mocker.patch("breba_app.mcp_api.router.save_files",
                 mocker.AsyncMock(side_effect=RuntimeError("R2 write failed")))
    preview = mocker.patch("breba_app.mcp_api.router.build_preview_incremental",
                           mocker.AsyncMock())
    content = base64.b64encode(b"x").decode()
    with pytest.raises(RuntimeError, match="R2 write failed"):
        client.post("/mcp/push", headers=bearer,
                    json={"files": [{"path": "a.css", "content_b64": content}]})
    preview.assert_not_called()


def test_push_preview_failure_reports_the_saved_version(client, bearer, existing_store, mocker):
    # The push persisted even though the preview build blew up (e.g. a broken
    # Jinja template): the error must say so, so the client doesn't re-push the
    # same files and stack identical broken versions.
    _, save = existing_store
    mocker.patch("breba_app.mcp_api.router.build_preview_incremental",
                 mocker.AsyncMock(side_effect=RuntimeError("unexpected end of template")))
    content = base64.b64encode(b"<new>").decode()
    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": "index.html", "content_b64": content}]})
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "saved as version 7" in detail
    assert "unexpected end of template" in detail
    assert save.await_count == 1


def test_push_preview_failure_still_overlays_live_session(client, bearer, existing_store, mocker):
    # The files are durably saved, so a stale open chat session must be updated
    # even when the preview build fails — otherwise its next persist would
    # silently revert the push.
    mocker.patch("breba_app.mcp_api.router.build_preview_incremental",
                 mocker.AsyncMock(side_effect=RuntimeError("boom")))
    live_store = InMemoryFileStore()
    live_store.write_bytes("index.html", b"<old>")
    mocker.patch("breba_app.mcp_api.router.state_exists", return_value=True)
    mocker.patch("breba_app.mcp_api.router.load_state",
                 return_value=mocker.Mock(filestore=live_store))
    content = base64.b64encode(b"<new>").decode()
    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": "index.html", "content_b64": content}]})
    assert resp.status_code == 500
    assert live_store.read_bytes("index.html") == b"<new>"


def test_push_to_missing_product_is_404(client, bearer, mocker):
    product = mocker.patch("breba_app.mcp_api.router.Product")
    product.find_one = mocker.AsyncMock(return_value=None)  # product missing
    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": "index.html", "content_b64": "Zm9v"}]})
    assert resp.status_code == 404


def test_push_invalid_base64_is_400(client, bearer, existing_store):
    resp = client.post("/mcp/push", headers=bearer,
                       json={"files": [{"path": "index.html", "content_b64": "!!!not-base64!!!"}]})
    assert resp.status_code == 400


# --- /mcp/file/stat: metadata without a download -------------------------------

def test_file_stat_returns_manifest_metadata(client, bearer, mocker):
    stat = mocker.patch(
        "breba_app.mcp_api.store.stat_file",
        mocker.AsyncMock(return_value={"size": 12345, "content_type": "image/png"}))
    resp = client.get("/mcp/file/stat", params={"path": "logo.png", "version": 5}, headers=bearer)
    assert resp.status_code == 200
    assert resp.json() == {"path": "logo.png", "size": 12345, "content_type": "image/png"}
    stat.assert_awaited_once_with(USER_ID, PRODUCT_ID, "logo.png", 5)


def test_file_stat_missing_file_is_404(client, bearer, mocker):
    mocker.patch("breba_app.mcp_api.store.stat_file",
                 mocker.AsyncMock(side_effect=NotFound("nope.png not found in version 3")))
    resp = client.get("/mcp/file/stat", params={"path": "nope.png"}, headers=bearer)
    assert resp.status_code == 404
    assert "nope.png" in resp.json()["detail"]


def test_file_stat_invalid_path_is_400(client, bearer):
    resp = client.get("/mcp/file/stat", params={"path": "../evil"}, headers=bearer)
    assert resp.status_code == 400


# --- store.stat_file: version resolution ---------------------------------------

def _stat_fs(mocker, active_version):
    fs = mocker.Mock()
    fs.get_version.return_value = active_version
    fs._prefix = "u1/p1"
    fs._bucket = "users"
    mocker.patch("breba_app.mcp_api.store._filesystem", return_value=fs)
    return fs


def test_stat_file_reads_manifest_for_versioned_products(mocker):
    fs = _stat_fs(mocker, active_version=3)
    fs._get_manifest.return_value = {"files": {
        "styles.css": {"key": "k", "size": 6, "content_type": "text/css"},
    }}
    meta = asyncio.run(store_module.stat_file("u1", "p1", "styles.css"))
    assert meta == {"size": 6, "content_type": "text/css"}
    fs._get_manifest.assert_called_once_with(3)


def test_stat_file_version_0_heads_the_unversioned_object(mocker):
    # Legacy pre-versioning products: read_file's version-0 branch serves the
    # unversioned object directly, so stat must resolve the same way instead of
    # 404ing on the placeholder v0 manifest.
    fs = _stat_fs(mocker, active_version=0)
    fs._s3.head_object.return_value = {"ContentLength": 42, "ContentType": "text/css"}
    meta = asyncio.run(store_module.stat_file("u1", "p1", "styles.css"))
    assert meta == {"size": 42, "content_type": "text/css"}
    fs._s3.head_object.assert_called_once_with(Bucket="users", Key="u1/p1/styles.css")
    fs._get_manifest.assert_not_called()


def test_stat_file_version_0_missing_object_is_not_found(mocker):
    from botocore.exceptions import ClientError

    fs = _stat_fs(mocker, active_version=0)
    fs._s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
    with pytest.raises(NotFound, match="version 0"):
        asyncio.run(store_module.stat_file("u1", "p1", "nope.css"))


def test_stat_file_missing_from_versioned_manifest_is_not_found(mocker):
    fs = _stat_fs(mocker, active_version=3)
    fs._get_manifest.return_value = {"files": {}}
    with pytest.raises(NotFound, match="nope.css not found in version 3"):
        asyncio.run(store_module.stat_file("u1", "p1", "nope.css"))


# --- store.list_files / store.read_file: single version resolution -------------
# The router tests fake these helpers, so their real version-resolution contract
# — "resolve None to the active version exactly once, and report that version
# back" — is pinned here, against the filesystem boundary.

def _read_fs(mocker, active_version):
    fs = mocker.Mock()
    fs.get_version.return_value = active_version
    fs.read_file = mocker.AsyncMock()
    mocker.patch("breba_app.mcp_api.store._filesystem", return_value=fs)
    return fs


def test_store_list_files_resolves_the_active_version_once(mocker):
    fs = _read_fs(mocker, active_version=3)
    fs.list_files.return_value = ["a.html", "b.css"]

    assert asyncio.run(store_module.list_files("u1", "p1")) == (["a.html", "b.css"], 3)

    # The listed manifest is exactly the resolved version reported back.
    fs.list_files.assert_called_once_with(3)
    fs.get_version.assert_called_once_with()


def test_store_list_files_passes_an_explicit_version_through(mocker):
    fs = _read_fs(mocker, active_version=3)
    fs.list_files.return_value = ["a.html"]

    assert asyncio.run(store_module.list_files("u1", "p1", version=5)) == (["a.html"], 5)

    fs.list_files.assert_called_once_with(5)
    fs.get_version.assert_not_called()


def test_store_read_file_resolves_the_active_version_once(mocker):
    fs = _read_fs(mocker, active_version=3)
    fw = FileWrite(path="a.html", content=b"<a>")
    fs.read_file.return_value = fw

    assert asyncio.run(store_module.read_file("u1", "p1", "a.html")) == (fw, 3)

    fs.read_file.assert_awaited_once_with("a.html", version=3)


def test_store_read_file_passes_an_explicit_version_through(mocker):
    fs = _read_fs(mocker, active_version=3)
    fw = FileWrite(path="a.html", content=b"<v5>")
    fs.read_file.return_value = fw

    assert asyncio.run(store_module.read_file("u1", "p1", "a.html", version=5)) == (fw, 5)

    fs.read_file.assert_awaited_once_with("a.html", version=5)
    fs.get_version.assert_not_called()


def test_store_read_file_propagates_not_found(mocker):
    fs = _read_fs(mocker, active_version=3)
    fs.read_file.side_effect = NotFound("a.html not found in version 3")
    with pytest.raises(NotFound, match="a.html not found"):
        asyncio.run(store_module.read_file("u1", "p1", "a.html"))


# --- store.read_all_files: bulk read for the push path ------------------------

def test_read_all_files_resolves_manifest_once_and_reads_by_key(mocker):
    fs = mocker.Mock()
    fs.get_version.return_value = 3
    fs._get_manifest.return_value = {"files": {
        "index.html": {"key": "u1/p1/versions/3/index.html"},
        "styles.css": {"key": "u1/p1/versions/2/styles.css"},  # carried forward from v2
    }}
    mocker.patch("breba_app.mcp_api.store._filesystem", return_value=fs)
    mocker.patch("breba_app.mcp_api.store.Settings", SimpleNamespace(USERS_BUCKET="users"))
    s3 = mocker.Mock()
    s3.get_object.side_effect = lambda Bucket, Key: {
        "Body": SimpleNamespace(read=lambda: f"<{Key}>".encode()),
        "ContentType": "text/html",
    }
    mocker.patch("breba_app.mcp_api.store.get_s3_client", return_value=s3)

    result = asyncio.run(store_module.read_all_files("u1", "p1"))

    # Each file is fetched by its manifest key (which may point at an older
    # version's object), after a single version+manifest resolution.
    assert result.read_bytes("index.html") == b"<u1/p1/versions/3/index.html>"
    assert result.read_bytes("styles.css") == b"<u1/p1/versions/2/styles.css>"
    fs._get_manifest.assert_called_once_with(3)
    assert all(kw["Bucket"] == "users" for _, kw in s3.get_object.call_args_list)


# --- preview.build_preview_incremental: skip unchanged uploads ----------------

def _run_incremental_preview(mocker, files: dict[str, bytes], existing_etags: dict[str, str]):
    from breba_app.mcp_api import preview as preview_module

    store = InMemoryFileStore()
    for path, content in files.items():
        store.write_bytes(path, content)
    # The Jinja build step is exercised by the builder's own tests; identity here.
    mocker.patch("breba_app.mcp_api.preview.build", side_effect=lambda fs: fs)
    mocker.patch("breba_app.mcp_api.preview._list_preview_etags",
                 return_value=existing_etags)
    bucket = mocker.Mock()
    asyncio.run(preview_module.build_preview_incremental(PRODUCT_ID, store, bucket=bucket))
    return bucket


def test_incremental_preview_skips_byte_identical_files(mocker):
    import hashlib

    css = b"body{}"
    bucket = _run_incremental_preview(
        mocker,
        files={"index.html": b"<p>hi</p>", "styles.css": css},
        existing_etags={f"{PRODUCT_ID}/styles.css": hashlib.md5(css).hexdigest()},
    )
    uploaded = [kw["Key"] for _, kw in bucket.put_object.call_args_list]
    assert uploaded == [f"{PRODUCT_ID}/index.html"]  # unchanged css not re-uploaded


def test_incremental_preview_reuploads_changed_and_unlisted_files(mocker):
    import hashlib

    bucket = _run_incremental_preview(
        mocker,
        files={"styles.css": b"body{color:red}", "logo.svg": b"<svg/>"},
        existing_etags={f"{PRODUCT_ID}/styles.css": hashlib.md5(b"body{}").hexdigest()},
    )
    uploaded = sorted(kw["Key"] for _, kw in bucket.put_object.call_args_list)
    assert uploaded == [f"{PRODUCT_ID}/logo.svg", f"{PRODUCT_ID}/styles.css"]


def test_incremental_preview_render_failure_names_files_and_uploads_the_rest(mocker):
    # This raised RuntimeError is what the router turns into its "saved as
    # version N, don't re-push" 500 — the router tests fake the raise, so the
    # real collect-failures-then-raise behavior is pinned here. The healthy
    # files must still reach the bucket first (mirrors build_preview's
    # per-file skip), so one corrupt asset doesn't hold back the whole preview.
    from breba_app.mcp_api import preview as preview_module

    class FlakyStore(InMemoryFileStore):
        def read_bytes(self, path):
            if path == "bad.bin":
                raise IOError("corrupt object")
            return super().read_bytes(path)

    store = FlakyStore()
    store.write_bytes("index.html", b"<p>hi</p>")
    store.write_bytes("bad.bin", b"\x00")
    mocker.patch("breba_app.mcp_api.preview.build", side_effect=lambda fs: fs)
    mocker.patch("breba_app.mcp_api.preview._list_preview_etags", return_value={})
    bucket = mocker.Mock()

    with pytest.raises(RuntimeError, match="bad.bin"):
        asyncio.run(preview_module.build_preview_incremental(PRODUCT_ID, store, bucket=bucket))

    uploaded = [kw["Key"] for _, kw in bucket.put_object.call_args_list]
    assert f"{PRODUCT_ID}/index.html" in uploaded


def _etag_pages(mocker, pages):
    s3 = mocker.Mock()
    s3.get_paginator.return_value.paginate.return_value = pages
    mocker.patch("breba_app.mcp_api.preview.get_s3_client", return_value=s3)
    return s3


def test_list_preview_etags_lists_the_given_bucket(mocker):
    # The skip decisions must be made against the bucket the writes go to.
    from breba_app.mcp_api import preview as preview_module

    s3 = _etag_pages(mocker, [{"Contents": [{"Key": "prod-1/a.css", "ETag": '"abc"'}]}])
    bucket = mocker.Mock()
    bucket.name = "custom-bucket"

    etags = preview_module._list_preview_etags(PRODUCT_ID, bucket)

    assert etags == {"prod-1/a.css": "abc"}
    s3.get_paginator.return_value.paginate.assert_called_once_with(
        Bucket="custom-bucket", Prefix=f"{PRODUCT_ID}/")


def test_list_preview_etags_defaults_to_the_public_bucket(mocker):
    from breba_app.mcp_api import preview as preview_module

    s3 = _etag_pages(mocker, [{}])  # page without Contents (empty prefix)
    mocker.patch("breba_app.mcp_api.preview.Settings",
                 SimpleNamespace(PUBLIC_BUCKET="public"))

    assert preview_module._list_preview_etags(PRODUCT_ID) == {}
    s3.get_paginator.return_value.paginate.assert_called_once_with(
        Bucket="public", Prefix=f"{PRODUCT_ID}/")


# --- /mcp/products: list the token owner's products ---------------------------

def test_list_products_returns_owned_products_and_current(client, mocker):
    user_oid = "a1b2c3d4e5f6a7b8c9d0e1f2"  # /mcp/products parses user_id as an ObjectId
    headers = {"Authorization": f"Bearer {auth.mint_token(user_oid, PRODUCT_ID)[0]}"}
    owned = [SimpleNamespace(product_id="prod-1", name="Boat Site"),
             SimpleNamespace(product_id="prod-2", name=None)]  # unnamed -> id as name
    product = mocker.patch("breba_app.mcp_api.products.Product")
    query = mocker.Mock()
    query.to_list = mocker.AsyncMock(return_value=owned)
    product.find.return_value = query

    resp = client.get("/mcp/products", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == {
        "products": [{"id": "prod-1", "name": "Boat Site"},
                     {"id": "prod-2", "name": "prod-2"}],
        "current": PRODUCT_ID,
    }


def test_list_products_requires_token(client):
    assert client.get("/mcp/products").status_code == 401
