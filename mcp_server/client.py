"""Thin HTTP client for the product's ``/mcp/*`` API.

Attaches ``Authorization: Bearer <token>`` from the token provider. On a ``401``
it forces a token refresh (the loopback browser flow) and retries the request
once, so the agent's first tool call transparently triggers sign-in.

Each instance holds one ``httpx.Client``, so consecutive tool calls reuse the
same TCP/TLS connection instead of paying a fresh handshake per request. The
pool lives for the process (one agent session); it is not explicitly closed.
"""
import httpx

from mcp_server.auth import TokenProvider


class SiteApiError(RuntimeError):
    """API call failed; ``status_code`` lets callers react per HTTP status."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class SiteClient:
    def __init__(self, base_url: str, token_provider: TokenProvider, timeout: float = 60.0):
        self._token_provider = token_provider
        self._http = httpx.Client(base_url=base_url, timeout=timeout)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        def call(token: str) -> httpx.Response:
            return self._http.request(
                method, path,
                headers={"Authorization": f"Bearer {token}"}, **kwargs,
            )

        resp = call(self._token_provider(False))
        if resp.status_code == 401:
            resp = call(self._token_provider(True))  # re-auth via browser, retry once
        if resp.status_code >= 400:
            raise SiteApiError(f"{method} {path} -> {resp.status_code}: {resp.text}",
                               resp.status_code)
        return resp.json()

    def ensure_auth(self) -> None:
        """Acquire a token now (cached, or the browser flow on first use).

        Lets callers force auth side effects — notably a consent-picker product
        switch retargeting the session — to happen *before* they read session
        state that depends on the target product.
        """
        self._token_provider(False)

    def list_versions(self) -> dict:
        return self._request("GET", "/mcp/versions")

    def list_files(self, version: int | None = None) -> dict:
        params = {} if version is None else {"version": version}
        return self._request("GET", "/mcp/files", params=params)

    def read_file(self, path: str, version: int | None = None) -> dict:
        params: dict = {"path": path}
        if version is not None:
            params["version"] = version
        return self._request("GET", "/mcp/file", params=params)

    def stat_file(self, path: str, version: int | None = None) -> dict:
        params: dict = {"path": path}
        if version is not None:
            params["version"] = version
        return self._request("GET", "/mcp/file/stat", params=params)

    def push(self, files: list[dict], expected_version: int | None = None) -> dict:
        body: dict = {"files": files}
        if expected_version is not None:
            body["expected_version"] = expected_version
        return self._request("POST", "/mcp/push", json=body)

    def preview(self) -> dict:
        return self._request("GET", "/mcp/preview")

    def products(self) -> dict:
        return self._request("GET", "/mcp/products")
