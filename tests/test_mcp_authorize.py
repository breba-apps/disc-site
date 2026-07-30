import asyncio
import time
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from breba_app.mcp_api import auth
from breba_app.mcp_api import authorize
from breba_app.mcp_api.authorize import optional_current_user, router
from breba_app.paths import templates

SECRET = "test-secret"
USER_ID = "uid-123"
PRODUCT_ID = "prod-1"


class _Page(HTMLParser):
    """Minimal structural view of a rendered page.

    Assert against parsed form inputs / anchor hrefs / option values instead of
    raw markup so a cosmetic template edit (class names, attribute order,
    whitespace) doesn't break the test while the behavior it guards is intact.
    """

    def __init__(self, html_text: str):
        super().__init__()
        self.inputs: dict[str, str] = {}   # input name -> value
        self.anchors: list[dict[str, str]] = []  # <a> attribute dicts
        self.options: list[str] = []       # <option> values
        self.feed(html_text)

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "input" and "name" in d:
            self.inputs[d["name"]] = d.get("value", "")
        elif tag == "a":
            self.anchors.append(d)
        elif tag == "option":
            self.options.append(d.get("value", ""))

    def anchor(self, **match) -> dict[str, str]:
        return next(a for a in self.anchors
                   if all(a.get(k) == v for k, v in match.items()))


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", SECRET)


@pytest.fixture(autouse=True)
def _fresh_consumed_codes():
    # The consumed-nonce registry is module-level state; clear it so test order
    # doesn't matter.
    auth.reset_consumed_codes()


@pytest.fixture(autouse=True)
def _asset_global():
    # base.html uses {{ asset(...) }}; main.py sets this at import — stub it for tests.
    templates.env.globals.setdefault("asset", lambda name: f"/public/{name}")


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False)


def _login_as(app, identifier="alice"):
    app.dependency_overrides[optional_current_user] = lambda: SimpleNamespace(identifier=identifier)


def _patch_db(mocker, products, find_one_product=None):
    db_user = SimpleNamespace(id=USER_ID, username="alice")
    user = mocker.patch("breba_app.mcp_api.authorize.User")
    user.find_one = mocker.AsyncMock(return_value=db_user)
    product = mocker.patch("breba_app.mcp_api.products.Product")
    query = mocker.MagicMock()
    query.to_list = mocker.AsyncMock(return_value=products)
    product.find.return_value = query
    product.find_one = mocker.AsyncMock(return_value=find_one_product)
    return user, product


def _make_product(product_id=PRODUCT_ID, name="BoatFix Pro"):
    return SimpleNamespace(product_id=product_id, name=name)


# --- loopback validation -----------------------------------------------------

@pytest.mark.parametrize("uri,ok", [
    ("http://127.0.0.1:54321/callback", True),
    ("http://localhost:8765/callback", True),
    ("https://localhost:8765/callback", True),
    ("http://evil.example.com/callback", False),
    ("ftp://127.0.0.1/callback", False),
    ("not-a-url", False),
])
def test_is_loopback(uri, ok):
    assert authorize._is_loopback(uri) is ok


# --- optional_current_user: resolve the Chainlit session, or None -------------
# Every other test overrides this dependency, so its real body — including the
# swallow-HTTPException-to-None path a bad cookie relies on — is pinned here.

def test_optional_current_user_returns_none_without_a_session_token(mocker):
    authenticate = mocker.patch("breba_app.mcp_api.authorize.authenticate_user")
    assert asyncio.run(optional_current_user(None)) is None
    authenticate.assert_not_called()


def test_optional_current_user_resolves_a_valid_session(mocker):
    user = SimpleNamespace(identifier="alice")
    mocker.patch("breba_app.mcp_api.authorize.authenticate_user",
                 mocker.AsyncMock(return_value=user))
    assert asyncio.run(optional_current_user("good-token")) is user


def test_optional_current_user_swallows_a_rejected_session(mocker):
    # A bad/expired cookie must yield None so the flow renders the sign-in page,
    # not raise and turn the authorize request into a 500.
    mocker.patch("breba_app.mcp_api.authorize.authenticate_user",
                 mocker.AsyncMock(side_effect=HTTPException(status_code=401)))
    assert asyncio.run(optional_current_user("stale-token")) is None


# --- POST /mcp/token : code -> bearer token ----------------------------------

def test_token_exchange_returns_valid_bearer(client):
    code = auth.mint_code(USER_ID, PRODUCT_ID)
    resp = client.post("/mcp/token", json={"code": code})
    assert resp.status_code == 200
    body = resp.json()
    assert body["product_id"] == PRODUCT_ID
    assert body["expires_at"] > time.time()
    data = auth.verify_token(body["token"])
    assert data["user_id"] == USER_ID
    assert data["product_id"] == PRODUCT_ID


def test_token_exchange_rejects_invalid_code(client):
    resp = client.post("/mcp/token", json={"code": "garbage"})
    assert resp.status_code == 400


def test_token_exchange_rejects_expired_code(client):
    resp = client.post("/mcp/token", json={"code": auth.mint_code(USER_ID, PRODUCT_ID, ttl=-10)})
    assert resp.status_code == 400


def test_token_exchange_rejects_a_bearer_token_as_code(client):
    # A long-lived bearer token must not be accepted at the code-exchange endpoint.
    resp = client.post("/mcp/token", json={"code": auth.mint_token(USER_ID, PRODUCT_ID)[0]})
    assert resp.status_code == 400


def test_token_exchange_is_single_use(client):
    # A leaked code must not mint a second bearer within its TTL.
    code = auth.mint_code(USER_ID, PRODUCT_ID)
    assert client.post("/mcp/token", json={"code": code}).status_code == 200
    assert client.post("/mcp/token", json={"code": code}).status_code == 400


# --- PKCE (RFC 7636, S256) -----------------------------------------------------

VERIFIER = "correct-horse-battery-staple"


def _pkce_code():
    return auth.mint_code(USER_ID, PRODUCT_ID,
                          code_challenge=auth.make_code_challenge(VERIFIER))


def test_token_exchange_accepts_matching_verifier(client):
    resp = client.post("/mcp/token", json={"code": _pkce_code(), "code_verifier": VERIFIER})
    assert resp.status_code == 200
    assert auth.verify_token(resp.json()["token"])["user_id"] == USER_ID


def test_token_exchange_rejects_wrong_verifier(client):
    resp = client.post("/mcp/token", json={"code": _pkce_code(), "code_verifier": "wrong"})
    assert resp.status_code == 400
    assert "code_verifier" in resp.json()["detail"]


def test_token_exchange_rejects_missing_verifier_when_code_has_challenge(client):
    assert client.post("/mcp/token", json={"code": _pkce_code()}).status_code == 400


def test_failed_pkce_attempt_burns_the_code(client):
    # The code is consumed before the verifier check, so an attacker who
    # intercepted it can't probe verifiers: one wrong guess invalidates it.
    code = _pkce_code()
    assert client.post("/mcp/token", json={"code": code, "code_verifier": "wrong"}).status_code == 400
    assert client.post("/mcp/token", json={"code": code, "code_verifier": VERIFIER}).status_code == 400


def test_code_without_challenge_needs_no_verifier(client):
    # PKCE is client-initiated defense in depth; codes minted without a
    # challenge still exchange (loopback + single-use remain in force).
    code = auth.mint_code(USER_ID, PRODUCT_ID)
    assert client.post("/mcp/token", json={"code": code}).status_code == 200


# --- verify_code purity vs consume_code one-shot ------------------------------

def test_verify_code_stays_pure_and_consume_code_is_one_shot():
    code = auth.mint_code(USER_ID, PRODUCT_ID)
    assert auth.verify_code(code) is not None
    assert auth.verify_code(code) is not None  # no side effects
    assert auth.consume_code(code) is not None
    assert auth.consume_code(code) is None
    assert auth.verify_code(code) is not None  # still pure after consumption


# --- GET /mcp/authorize : consent page ---------------------------------------

def test_authorize_signin_page_preserves_the_authorize_url(app, client):
    # The query is the one-time authorize request the waiting MCP server minted,
    # and /login has no return-redirect — a plain login link would orphan the
    # flow at "/" until the loopback wait times out. The page must open sign-in
    # in a new tab and offer a continue link that re-hits this very URL.
    app.dependency_overrides[optional_current_user] = lambda: None
    params = {"redirect_uri": "http://127.0.0.1:54321/callback",
              "state": "xyz", "product_id": PRODUCT_ID, "code_challenge": "chall-abc"}
    resp = client.get("/mcp/authorize", params=params)
    assert resp.status_code == 401
    page = _Page(resp.text)

    # Sign-in opens in a new tab so it doesn't navigate this page away.
    assert page.anchor(href="/login")["target"] == "_blank"

    # The continue link re-hits this authorize URL, carrying the whole one-time
    # request so the flow isn't orphaned after login.
    cont = next(a for a in page.anchors if a["href"].startswith("/mcp/authorize?"))
    assert parse_qs(urlparse(cont["href"]).query) == {k: [v] for k, v in params.items()}


def test_authorize_rejects_non_loopback_redirect(app, client):
    _login_as(app)
    resp = client.get("/mcp/authorize",
                      params={"redirect_uri": "http://evil.example.com/callback"})
    assert resp.status_code == 400
    assert "loopback" in resp.text


def test_authorize_renders_consent_with_product(app, client, mocker):
    _login_as(app)
    _patch_db(mocker, products=[_make_product()])
    resp = client.get("/mcp/authorize", params={
        "redirect_uri": "http://127.0.0.1:54321/callback",
        "state": "xyz", "product_id": PRODUCT_ID, "code_challenge": "chall-abc",
    })
    assert resp.status_code == 200
    page = _Page(resp.text)
    assert "Authorize coding agent" in resp.text  # consent heading
    assert "BoatFix Pro" in resp.text             # product name rendered
    assert page.inputs["state"] == "xyz"          # state carried into the form
    assert page.inputs["code_challenge"] == "chall-abc"  # PKCE challenge too
    assert PRODUCT_ID in page.options             # owned product offered


def test_approve_embeds_code_challenge_in_the_code(app, client, mocker):
    _login_as(app)
    _patch_db(mocker, products=[_make_product()], find_one_product=_make_product())
    resp = client.post("/mcp/authorize", data={
        "redirect_uri": "http://127.0.0.1:54321/callback",
        "state": "xyz", "product_id": PRODUCT_ID, "decision": "approve",
        "code_challenge": "chall-abc",
    })
    assert resp.status_code == 303
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert auth.verify_code(qs["code"][0])["code_challenge"] == "chall-abc"


def test_authorize_unknown_product_redirects_with_error(app, client, mocker):
    # An error page here would never redirect to the loopback callback and the
    # local MCP server would hang — the error must go back via the redirect.
    _login_as(app)
    _patch_db(mocker, products=[_make_product()])
    resp = client.get("/mcp/authorize", params={
        "redirect_uri": "http://127.0.0.1:54321/callback",
        "state": "xyz", "product_id": "not-mine",
    })
    assert resp.status_code == 303
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert qs["error"] == ["invalid_product"]
    assert "not-mine" in qs["error_description"][0]
    assert qs["state"] == ["xyz"]


def test_authorize_no_products_redirects_with_error(app, client, mocker):
    _login_as(app)
    _patch_db(mocker, products=[])
    resp = client.get("/mcp/authorize", params={
        "redirect_uri": "http://127.0.0.1:54321/callback", "state": "xyz",
    })
    assert resp.status_code == 303
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert qs["error"] == ["no_products"]
    assert qs["state"] == ["xyz"]


# --- POST /mcp/authorize : consent decision ----------------------------------

def test_approve_redirects_to_loopback_with_valid_code(app, client, mocker):
    _login_as(app)
    _patch_db(mocker, products=[_make_product()], find_one_product=_make_product())
    resp = client.post("/mcp/authorize", data={
        "redirect_uri": "http://127.0.0.1:54321/callback",
        "state": "xyz", "product_id": PRODUCT_ID, "decision": "approve",
    })
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("http://127.0.0.1:54321/callback?")
    qs = parse_qs(urlparse(location).query)
    assert qs["state"] == ["xyz"]
    data = auth.verify_code(qs["code"][0])
    assert data["user_id"] == USER_ID
    assert data["product_id"] == PRODUCT_ID


def test_deny_redirects_with_access_denied(app, client, mocker):
    _login_as(app)
    _patch_db(mocker, products=[_make_product()])
    resp = client.post("/mcp/authorize", data={
        "redirect_uri": "http://127.0.0.1:54321/callback",
        "state": "xyz", "product_id": PRODUCT_ID, "decision": "deny",
    })
    assert resp.status_code == 303
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert qs["error"] == ["access_denied"]
    assert qs["state"] == ["xyz"]


def test_approve_unowned_product_redirects_with_error(app, client, mocker):
    _login_as(app)
    _patch_db(mocker, products=[_make_product()], find_one_product=None)
    resp = client.post("/mcp/authorize", data={
        "redirect_uri": "http://127.0.0.1:54321/callback",
        "state": "xyz", "product_id": "not-mine", "decision": "approve",
    })
    assert resp.status_code == 303
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert qs["error"] == ["invalid_product"]
    assert qs["state"] == ["xyz"]


def test_approve_expired_session_redirects_with_error(app, client):
    app.dependency_overrides[optional_current_user] = lambda: None
    resp = client.post("/mcp/authorize", data={
        "redirect_uri": "http://127.0.0.1:54321/callback",
        "state": "xyz", "product_id": PRODUCT_ID, "decision": "approve",
    })
    assert resp.status_code == 303
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert qs["error"] == ["session_expired"]
    assert qs["state"] == ["xyz"]


def test_approve_non_loopback_redirect_is_400(app, client):
    _login_as(app)
    resp = client.post("/mcp/authorize", data={
        "redirect_uri": "http://evil.example.com/callback",
        "state": "xyz", "product_id": PRODUCT_ID, "decision": "approve",
    })
    assert resp.status_code == 400


# --- unlocatable account: Chainlit identity with no DB user --------------------

def _login_without_db_user(app, mocker):
    """Signed in via Chainlit, but no matching User document exists."""
    _login_as(app)
    user = mocker.patch("breba_app.mcp_api.authorize.User")
    user.find_one = mocker.AsyncMock(return_value=None)


def test_authorize_unlocatable_account_redirects_with_error(app, client, mocker):
    # Like every other terminal error, this must go back via the loopback
    # redirect — an error page would strand the waiting MCP server.
    _login_without_db_user(app, mocker)
    resp = client.get("/mcp/authorize", params={
        "redirect_uri": "http://127.0.0.1:54321/callback", "state": "xyz",
    })
    assert resp.status_code == 303
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert qs["error"] == ["account_not_found"]
    assert qs["state"] == ["xyz"]


def test_approve_unlocatable_account_redirects_with_error(app, client, mocker):
    _login_without_db_user(app, mocker)
    resp = client.post("/mcp/authorize", data={
        "redirect_uri": "http://127.0.0.1:54321/callback",
        "state": "xyz", "product_id": PRODUCT_ID, "decision": "approve",
    })
    assert resp.status_code == 303
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert qs["error"] == ["account_not_found"]
    assert qs["state"] == ["xyz"]


# --- consume_code under concurrency ---------------------------------------------

def test_concurrent_exchanges_of_one_code_have_a_single_winner():
    # The check-and-record runs under a lock: two exchanges of the same leaked
    # code racing each other must not both mint a bearer.
    import threading

    code = auth.mint_code(USER_ID, PRODUCT_ID)
    barrier = threading.Barrier(8)
    results = []

    def attempt():
        barrier.wait()
        results.append(auth.consume_code(code))

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(r is not None for r in results) == 1
