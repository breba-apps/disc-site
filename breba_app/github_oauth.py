import base64
import hashlib
import hmac
import json
import secrets
from urllib.parse import urlencode

import httpx

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_USER_URL = "https://api.github.com/user"
GITHUB_API_ORGS_URL = "https://api.github.com/user/orgs"


def build_github_auth_url(client_id: str, state: str) -> str:
    """Return GitHub OAuth authorization URL with repo and org scopes."""
    params = urlencode({
        "client_id": client_id,
        "scope": "repo read:org",
        "state": state,
    })
    return f"{GITHUB_AUTHORIZE_URL}?{params}"


def generate_state(username: str, secret: str) -> str:
    """Return a signed state token encoding the username.
    Format: base64(json({username, nonce})).hmac_sha256_sig
    """
    nonce = secrets.token_hex(16)
    payload = json.dumps({"username": username, "nonce": nonce})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_state(state: str, secret: str) -> str | None:
    """Verify state signature and return username, or None if invalid."""
    try:
        payload_b64, sig = state.split(".", 1)
        expected = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload_b64).decode())
        return data["username"]
    except Exception:
        return None


async def exchange_code_for_token(client_id: str, client_secret: str, code: str) -> str:
    """POST to GitHub token URL, return access_token string. Raise ValueError on error."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise ValueError(f"GitHub OAuth error: {data.get('error_description', data['error'])}")
        access_token = data.get("access_token")
        if not access_token:
            raise ValueError("No access_token in GitHub response")
        return access_token


async def get_github_username(token: str) -> str:
    """GET /user from GitHub API, return login string."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            GITHUB_API_USER_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["login"]


async def get_github_orgs(token: str) -> list[str]:
    """GET /user/orgs from GitHub API, return list of org login names."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            GITHUB_API_ORGS_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        return [org["login"] for org in response.json()]


