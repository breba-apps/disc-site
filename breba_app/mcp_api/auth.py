"""Stateless HMAC tokens for the headless MCP push API.

Generalizes the proven signing pattern in ``github_oauth.generate_state`` /
``verify_state`` from a bare username to an arbitrary dict payload. No new server
secret and no DB state: tokens are signed with the existing ``CHAINLIT_AUTH_SECRET``
and carry their own expiry.

Two payload kinds share one scheme:
- ``tok``  — the long-lived bearer token the agent sends on every request.
- ``code`` — a short-lived code used by the browser auth flow so the bearer
             token never lands in a redirect URL / browser history. Codes are
             single-use, enforced per-process via ``consume_code``: the tokens
             themselves are stateless, so a multi-worker deployment would need
             shared storage for the consumed-nonce registry (the app currently
             runs single-process — the same assumption the live-session overlay
             makes).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from fastapi import HTTPException, Request

DEFAULT_TOKEN_TTL = 30 * 24 * 3600  # 30 days
DEFAULT_CODE_TTL = 60               # seconds


def _secret() -> str:
    s = os.environ.get("CHAINLIT_AUTH_SECRET", "")
    if not s:
        raise RuntimeError("CHAINLIT_AUTH_SECRET not set")
    return s


def _sign(payload: dict) -> str:
    """Return ``base64url(json(payload)).hmac_sha256`` (same shape as github_oauth)."""
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(_secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify(token: str) -> dict | None:
    """Return the payload if signature is valid and unexpired, else None.

    A missing ``CHAINLIT_AUTH_SECRET`` is server misconfiguration, not a bad
    token — the secret is resolved outside the ``except`` so the RuntimeError
    propagates (surfacing as a 500) instead of masquerading as a 401.
    """
    secret = _secret()
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(body).decode())
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


def _mint(kind: str, user_id: str, product_id: str, ttl: int,
          extra: dict | None = None) -> tuple[str, dict]:
    payload = {"t": kind, "user_id": user_id, "product_id": product_id,
               "exp": time.time() + ttl, **(extra or {})}
    return _sign(payload), payload


def mint_token(user_id: str, product_id: str,
               ttl: int = DEFAULT_TOKEN_TTL) -> tuple[str, dict]:
    """Bearer token plus its payload, so callers that need the authoritative
    ``exp`` never re-verify a token they just signed themselves."""
    return _mint("tok", user_id, product_id, ttl)


def verify_token(token: str) -> dict | None:
    data = _verify(token)
    return data if data and data.get("t") == "tok" else None


def mint_code(user_id: str, product_id: str, ttl: int = DEFAULT_CODE_TTL,
              code_challenge: str = "") -> str:
    """Mint a browser code; a non-empty ``code_challenge`` (PKCE S256) rides in
    the signed payload, so the binding needs no server-side state.

    Only codes carry a ``nonce``: it exists for ``consume_code``'s single-use
    accounting, which bearer tokens deliberately don't have."""
    extra = {"nonce": secrets.token_hex(8)}
    if code_challenge:
        extra["code_challenge"] = code_challenge
    return _mint("code", user_id, product_id, ttl, extra)[0]


def verify_code(code: str) -> dict | None:
    """Pure signature/expiry check — no single-use accounting (see consume_code)."""
    data = _verify(code)
    return data if data and data.get("t") == "code" else None


def make_code_challenge(verifier: str) -> str:
    """PKCE S256 transform (RFC 7636): unpadded base64url of sha256(verifier)."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def code_challenge_matches(verifier: str, challenge: str) -> bool:
    return hmac.compare_digest(make_code_challenge(verifier), challenge)


# Single-use enforcement for browser codes. Per-process only: a multi-worker
# deployment would need shared storage. Entries live at most DEFAULT_CODE_TTL
# past minting, so the registry stays tiny; expired entries are pruned on access.
_consumed_nonces: dict[str, float] = {}  # nonce -> exp
_consumed_lock = threading.Lock()


def reset_consumed_codes() -> None:
    """Clear the consumed-nonce registry (test isolation hook)."""
    with _consumed_lock:
        _consumed_nonces.clear()


def consume_code(code: str) -> dict | None:
    """Verify a browser code AND mark it consumed; None if invalid or already used.

    The check-and-record happens under a lock so two concurrent exchanges of the
    same leaked code cannot both succeed.
    """
    data = verify_code(code)
    if not data:
        return None
    nonce = data.get("nonce", "")
    now = time.time()
    with _consumed_lock:
        for n in [n for n, exp in _consumed_nonces.items() if exp < now]:
            del _consumed_nonces[n]
        if nonce in _consumed_nonces:
            return None
        _consumed_nonces[nonce] = data["exp"]
    return data


def require_push_token(request: Request) -> dict:
    """FastAPI dependency: authenticate via ``Authorization: Bearer <token>``.

    Replaces both the Chainlit cookie auth and the in-memory ``state_exists``
    session requirement that the browser ``/upload`` path depends on. On any
    failure, 401 with a ``WWW-Authenticate`` pointer so the MCP client knows to
    start the browser flow at ``/mcp/authorize``.
    """
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    data = verify_token(token)
    if not data:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid token; authorize at /mcp/authorize",
            headers={"WWW-Authenticate": 'Bearer realm="/mcp/authorize"'},
        )
    return data  # {"user_id", "product_id", ...}
