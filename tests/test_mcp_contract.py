"""Contract tests: the real MCP tools and SiteClient against the real /mcp router.

The unit suites for the two halves (tests/test_mcp_server.py, tests/test_mcp_api.py)
each mock the other side of the HTTP seam, so neither can catch drift in the wire
contract — field names, query params, the bearer header, status codes. A misspelled
``expected_version`` key in SiteClient.push, for example, would pass every unit
test while pydantic silently dropped the field and disabled the concurrency guard
in production.

Here the local server's real code path (tool -> SiteClient -> httpx request
building) executes against the real FastAPI router (real ``require_push_token``,
real endpoint signatures), with only the storage/DB boundary mocked. Starlette's
``TestClient`` is itself an ``httpx.Client``, so patching the client's
``httpx.Client`` constructor routes real HTTP semantics into the in-process app.
Auth uses genuinely minted tokens via ``BREBA_MCP_TOKEN`` — no browser flow, and
the real ``ensure_auth``/token-provider path still runs.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from breba_app.filesystem.in_memory_store import InMemoryFileStore
from breba_app.filesystem.models import FileWrite
from breba_app.mcp_api import auth as api_auth
from breba_app.mcp_api.router import router
from mcp_server import server
from mcp_server.client import SiteApiError, SiteClient

USER_ID = "a1b2c3d4e5f6a7b8c9d0e1f2"  # /mcp/products parses user_id as an ObjectId
PRODUCT_ID = "prod-1"
BASE = "http://testserver"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "contract-secret")
    monkeypatch.setenv("BREBA_MCP_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BREBA_BASE_URL", BASE)
    monkeypatch.delenv("BREBA_PRODUCT_ID", raising=False)
    monkeypatch.delenv("BREBA_MCP_MAX_FILE_BYTES", raising=False)
    monkeypatch.setattr(server, "_product_override", None)
    monkeypatch.setattr(server, "_clients", {})
    monkeypatch.setattr(server, "_observed_versions", {})


@pytest.fixture
def api(mocker):
    """The real router on a real ASGI app; only the storage/DB boundary is mocked."""
    store = InMemoryFileStore()
    store.write_bytes("index.html", b"<old>")
    product = mocker.patch("breba_app.mcp_api.router.Product")
    product.find_one = mocker.AsyncMock(return_value=object())
    mocks = SimpleNamespace(
        stat=mocker.patch("breba_app.mcp_api.store.stat_file", mocker.AsyncMock(
            return_value={"size": 5, "content_type": "text/html"})),
        read=mocker.patch("breba_app.mcp_api.store.read_file", mocker.AsyncMock(
            return_value=(FileWrite(path="index.html", content=b"<old>"), 6))),
        list=mocker.patch("breba_app.mcp_api.store.list_files", mocker.AsyncMock(
            return_value=(["index.html"], 6))),
        read_all=mocker.patch("breba_app.mcp_api.store.read_all_files",
                              mocker.AsyncMock(return_value=store)),
        active=mocker.patch("breba_app.mcp_api.router.get_active_version",
                            mocker.AsyncMock(return_value=6)),
        save=mocker.patch("breba_app.mcp_api.router.save_files",
                          mocker.AsyncMock(return_value=7)),
        preview=mocker.patch("breba_app.mcp_api.router.build_preview_incremental",
                             mocker.AsyncMock()),
        index=mocker.patch("breba_app.mcp_api.router.get_index_html_path",
                           return_value="http://prod-1.localhost:8088/index.html"),
    )
    app = FastAPI()
    app.include_router(router)
    return app, mocks


def _route_wire_into(mocker, app):
    """Make SiteClient's own httpx.Client dispatch into the in-process app."""
    mocker.patch("mcp_server.client.httpx.Client", return_value=TestClient(app))


@pytest.fixture
def full_stack(api, mocker, monkeypatch):
    """Real tool -> real SiteClient -> real router, authed by a real minted token."""
    app, mocks = api
    monkeypatch.setenv("BREBA_MCP_TOKEN", api_auth.mint_token(USER_ID, PRODUCT_ID)[0])
    _route_wire_into(mocker, app)
    return mocks


# --- the optimistic-concurrency guard, end to end ------------------------------

def test_stale_push_is_rejected_across_the_real_wire(full_stack):
    # This is the test a client-side wire-format typo cannot survive: the
    # observed revision must reach the router's preflight under the exact field
    # name PushIn expects, or pydantic drops it and the push sails through.
    server.read_site_file("index.html")   # observes active revision 6
    full_stack.active.return_value = 7    # another edit landed since the read

    with pytest.raises(SiteApiError) as err:
        server.push_site([server.FileArg(path="index.html", content="<new>")])

    assert err.value.status_code == 409
    full_stack.save.assert_not_awaited()


def test_push_with_current_version_lands(full_stack):
    server.read_site_file("index.html")

    result = server.push_site([server.FileArg(path="index.html", content="<new>")])

    assert result == {"version": 7, "product_id": PRODUCT_ID}
    saved = full_stack.save.await_args.args[2]
    assert [(fw.path, fw.content) for fw in saved] == [("index.html", b"<new>")]


def test_unguarded_push_skips_the_version_preflight(full_stack):
    # No read happened: no expected_version may cross the wire, and the router
    # must not spend a round-trip resolving a version nobody compares against.
    result = server.push_site([server.FileArg(path="index.html", content="<new>")])

    assert result["version"] == 7
    full_stack.active.assert_not_awaited()


# --- auth handshake -------------------------------------------------------------

def test_expired_token_triggers_refresh_and_retry(api, mocker):
    # The real require_push_token rejects a genuinely expired token with a 401;
    # the real SiteClient must force-refresh and retry once, transparently.
    app, _ = api
    _route_wire_into(mocker, app)
    expired = api_auth.mint_token(USER_ID, PRODUCT_ID, ttl=-10)[0]
    fresh = api_auth.mint_token(USER_ID, PRODUCT_ID)[0]
    seen = []

    def provider(force_refresh=False):
        seen.append(force_refresh)
        return fresh if force_refresh else expired

    out = SiteClient(BASE, provider).list_files()

    assert out == {"files": ["index.html"], "version": 6}
    assert seen == [False, True]


# --- reads, params, and error mapping -------------------------------------------

def test_versioned_read_params_survive_the_wire(full_stack):
    full_stack.read.return_value = (FileWrite(path="index.html", content=b"<v5>"), 5)

    out = server.read_site_file("index.html", version=5)

    assert out == {"path": "index.html", "content": "<v5>"}
    # The query-param names the client sends are the ones the endpoints declare.
    full_stack.stat.assert_awaited_once_with(USER_ID, PRODUCT_ID, "index.html", 5)
    full_stack.read.assert_awaited_once_with(USER_ID, PRODUCT_ID, "index.html", 5)


def test_invalid_path_maps_to_400_across_the_wire(api, mocker):
    # The store contract raises ValueError for a bad path; the router must map
    # it to a 400 the client surfaces as a SiteApiError with that status.
    app, mocks = api
    _route_wire_into(mocker, app)
    mocks.read.side_effect = ValueError("bad path")
    client = SiteClient(BASE, lambda force=False: api_auth.mint_token(USER_ID, PRODUCT_ID)[0])

    with pytest.raises(SiteApiError) as err:
        client.read_file("../evil")

    assert err.value.status_code == 400


def test_products_and_preview_cross_the_wire(full_stack, mocker):
    owned = [SimpleNamespace(product_id=PRODUCT_ID, name="Boat Site")]
    product = mocker.patch("breba_app.mcp_api.products.Product")
    query = mocker.Mock()
    query.to_list = mocker.AsyncMock(return_value=owned)
    product.find.return_value = query

    assert server.list_products() == {
        "products": [{"id": PRODUCT_ID, "name": "Boat Site"}],
        "current": PRODUCT_ID,
    }
    assert server.get_preview_url() == {
        "preview_url": "http://prod-1.localhost:8088/index.html"}
