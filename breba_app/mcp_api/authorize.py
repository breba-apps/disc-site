"""SSO-gated browser authorization for the headless MCP push API.

Implements the interactive loopback flow (RFC 8252 "native app" pattern, like
``gh auth login``). It reuses the product's *existing* Chainlit / Google SSO
login — no new login system, no ``User`` schema change:

  1. The local MCP server opens ``GET /mcp/authorize?redirect_uri=&state=
     &product_id=&code_challenge=`` in the user's browser. ``code_challenge`` is
     the PKCE S256 hash (RFC 7636) of a verifier the MCP server keeps locally.
  2. The user signs in with the normal SSO/password (the Chainlit session cookie)
     and is shown a consent page: "Allow this agent to push to <product> as <you>?".
  3. On approve we mint a short-lived (60s) ``code`` and redirect to the loopback
     ``redirect_uri?code=&state=``. ``redirect_uri`` is restricted to loopback
     hosts so the code can't be exfiltrated to an arbitrary server. The code is
     single-use — enforced per-process by ``auth.consume_code`` (see ``auth.py``
     for the multi-worker caveat) — and carries the ``code_challenge`` inside its
     signed payload, so the PKCE binding needs no server-side state.
  4. The MCP server exchanges the code (plus the PKCE ``code_verifier``) at
     ``POST /mcp/token`` for the real, long-lived bearer token. Doing the swap
     server-side keeps the bearer token out of browser history / redirect logs;
     PKCE means a code intercepted in transit or from a log still can't be
     exchanged without the verifier, which never leaves the MCP server.

The token itself is the same stateless HMAC token from ``auth.py``, signed with
``CHAINLIT_AUTH_SECRET`` — the agent receives a *token*, never the server secret.

Terminal errors (wrong product ID, expired session, denied consent, …) are
redirected back to the loopback ``redirect_uri`` as ``error=`` /
``error_description=`` query params, OAuth-style, once ``redirect_uri`` has
passed the loopback check. Rendering an error page instead would strand the
local MCP server waiting for a callback that never comes. Only "sign in
required" (GET) and an invalid ``redirect_uri`` still render pages: the former
because the page keeps the one-time authorize URL alive (sign-in opens in a
new tab; a continue link re-hits the same URL once the session cookie exists),
the latter because the URI can't be trusted.

CSRF: the consent POST requires a same-origin ``Origin``/``Referer`` header
(``_same_origin``), so protection does not depend on the session cookie's
SameSite setting; the loopback-only ``redirect_uri`` remains a second layer.
"""
from urllib.parse import urlencode, urlparse

from chainlit.auth import authenticate_user, reuseable_oauth
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from breba_app.mcp_api.auth import (
    code_challenge_matches,
    consume_code,
    mint_code,
    mint_token,
)
from breba_app.mcp_api.products import owned_products, product_listing
from breba_app.models.user import User
from breba_app.paths import templates

router = APIRouter(prefix="/mcp", tags=["mcp"])

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


async def optional_current_user(session_token: str | None = Depends(reuseable_oauth)):
    """Resolve the logged-in Chainlit user, or ``None`` if not signed in.

    Unlike ``chainlit.auth.get_current_user``, this never raises on a missing or
    invalid session — the browser flow renders a friendly "sign in first" page
    instead of a bare 401.
    """
    if not session_token:
        return None
    try:
        return await authenticate_user(session_token)
    except HTTPException:
        return None


def _is_loopback(redirect_uri: str) -> bool:
    try:
        parsed = urlparse(redirect_uri)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and parsed.hostname in _LOOPBACK_HOSTS


def _same_origin(request: Request) -> bool:
    """CSRF check independent of the cookie's SameSite setting; fails closed."""
    src = request.headers.get("origin") or request.headers.get("referer")
    return bool(src) and urlparse(src).netloc == request.url.netloc


def _redirect_back(redirect_uri: str, **params: str) -> str:
    sep = "&" if urlparse(redirect_uri).query else "?"
    return f"{redirect_uri}{sep}{urlencode(params)}"


def _redirect_error(redirect_uri: str, error: str, description: str, state: str) -> RedirectResponse:
    """Send a terminal error back to the loopback callback (OAuth-style).

    Rendering an error page instead would leave the local MCP server waiting
    forever for a callback that never comes — the agent's tool call would hang.
    Only call this with an already-validated loopback ``redirect_uri``.
    """
    return RedirectResponse(
        _redirect_back(redirect_uri, error=error, error_description=description, state=state),
        status_code=303,
    )


def _message(request: Request, heading: str, message: str, status_code: int = 200,
             link_url: str | None = None, link_text: str | None = None,
             link_new_tab: bool = False, continue_url: str | None = None,
             continue_text: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "mcp_message.html",
        {"heading": heading, "message": message,
         "link_url": link_url, "link_text": link_text, "link_new_tab": link_new_tab,
         "continue_url": continue_url, "continue_text": continue_text},
        status_code=status_code,
    )


async def _resolve_owner(current_user, redirect_uri: str, state: str):
    """Map the signed-in Chainlit identity to its DB user and their products.

    Returns ``(db_user, products, None)`` on success, ``(None, None, error_redirect)``
    when the account can't be located — both handlers report that the same
    OAuth-style way. The products list is what the consent page renders and what
    the approval validates the requested product against, so both handlers load
    it here rather than issuing a separate per-product lookup.
    """
    db_user = await User.find_one(User.username == current_user.identifier)
    if not db_user:
        return None, None, _redirect_error(redirect_uri, "account_not_found",
                                           "Your account could not be located.", state)
    return db_user, await owned_products(db_user.id), None


def _invalid_product_error(redirect_uri: str, product_id: str, state: str) -> RedirectResponse:
    return _redirect_error(
        redirect_uri, "invalid_product",
        f"Product '{product_id}' does not exist or is not yours. "
        "Check BREBA_PRODUCT_ID and retry.", state,
    )


@router.get("/authorize", response_class=HTMLResponse)
async def authorize(request: Request, redirect_uri: str = "", state: str = "",
                    product_id: str = "", code_challenge: str = "",
                    current_user=Depends(optional_current_user)):
    if current_user is None:
        # This URL's query (redirect_uri, state, code_challenge, product_id) is
        # the one-time authorize request the waiting MCP server minted, and the
        # login flow has no "next"-style return redirect — after SSO the user
        # lands on "/". So sign-in opens in a new tab and this page keeps the
        # authorize URL alive itself: the continue link re-hits the same URL,
        # now with the session cookie present, and lands on the consent page.
        original_url = request.url.path + (
            f"?{request.url.query}" if request.url.query else "")
        return _message(
            request, "Sign in required",
            "Sign in to Breba in the new tab, then come back here and continue "
            "to authorize the agent.",
            status_code=401, link_url="/login", link_text="Sign in",
            link_new_tab=True,
            continue_url=original_url, continue_text="I've signed in — continue",
        )
    if not _is_loopback(redirect_uri):
        return _message(
            request, "Invalid request",
            "redirect_uri must be a loopback address (127.0.0.1 or localhost).",
            status_code=400,
        )

    _, products, error = await _resolve_owner(current_user, redirect_uri, state)
    if error:
        return error
    if not products:
        return _redirect_error(
            redirect_uri, "no_products",
            "You have no products yet. Create one in the Breba app, then retry.", state,
        )
    if product_id and not any(p.product_id == product_id for p in products):
        return _invalid_product_error(redirect_uri, product_id, state)

    return templates.TemplateResponse(
        request,
        "mcp_consent.html",
        {
            "username": current_user.identifier,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "selected_product_id": product_id,
            "products": product_listing(products),
        },
    )


@router.post("/authorize")
async def authorize_decision(request: Request, redirect_uri: str = Form(""),
                             state: str = Form(""), product_id: str = Form(""),
                             decision: str = Form(""), code_challenge: str = Form(""),
                             current_user=Depends(optional_current_user)):
    if not _is_loopback(redirect_uri):
        return _message(request, "Invalid request",
                        "redirect_uri must be a loopback address.", status_code=400)
    if not _same_origin(request):
        return _redirect_error(redirect_uri, "invalid_origin",
                               "Consent must be submitted from the Breba consent page.", state)
    if current_user is None:
        return _redirect_error(redirect_uri, "session_expired",
                               "Your Breba session expired. Sign in in the browser and retry.",
                               state)

    if decision != "approve":
        return RedirectResponse(
            _redirect_back(redirect_uri, error="access_denied", state=state),
            status_code=303,
        )

    db_user, products, error = await _resolve_owner(current_user, redirect_uri, state)
    if error:
        return error
    if not any(p.product_id == product_id for p in products):
        return _invalid_product_error(redirect_uri, product_id, state)

    code = mint_code(str(db_user.id), product_id, code_challenge=code_challenge)
    return RedirectResponse(
        _redirect_back(redirect_uri, code=code, state=state),
        status_code=303,
    )


class TokenIn(BaseModel):
    code: str
    code_verifier: str = ""


@router.post("/token")
async def token(body: TokenIn):
    """Exchange a single-use browser code for a long-lived bearer token.

    ``consume_code`` (not ``verify_code``) so a leaked code can't be exchanged
    twice — the second attempt gets the same 400 as an invalid code. When the
    code carries a PKCE challenge, the exchange must present the matching
    verifier; the code is consumed before the PKCE check, so a failed attempt
    burns it. Codes minted without a challenge (older or third-party clients)
    are still accepted — PKCE here is client-initiated defense in depth on top
    of the loopback-only redirect and single-use codes, not a mandate.
    """
    data = consume_code(body.code)
    if not data:
        raise HTTPException(400, detail="Invalid, expired, or already used code")
    challenge = data.get("code_challenge", "")
    if challenge and not code_challenge_matches(body.code_verifier, challenge):
        raise HTTPException(400, detail="code_verifier does not match the code's challenge")
    bearer, payload = mint_token(data["user_id"], data["product_id"])
    return {"token": bearer, "product_id": data["product_id"], "expires_at": payload["exp"]}
