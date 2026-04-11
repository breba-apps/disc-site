import asyncio
import base64
import logging
import re

import httpx

GITHUB_API_BASE = "https://api.github.com"

logger = logging.getLogger(__name__)


def _auth_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def slugify(name: str) -> str:
    """Convert a product name to a valid GitHub repo name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "breba-page"


async def create_repo(token: str, org: str, repo_name: str) -> dict:
    """Create a new public repo under an org.
    Returns repo info with 'name', 'full_name', 'html_url'.
    If repo_name is taken, appends -1, -2, ... until a free name is found.
    """
    async with httpx.AsyncClient() as client:
        candidate = repo_name
        suffix = 0
        while True:
            response = await client.post(
                f"{GITHUB_API_BASE}/orgs/{org}/repos",
                headers=_auth_headers(token),
                json={"name": candidate, "private": False, "auto_init": True},
            )
            if response.status_code == 201:
                return response.json()
            if response.status_code == 422:
                # Name conflict — try next suffix
                suffix += 1
                candidate = f"{repo_name}-{suffix}"
                continue
            response.raise_for_status()


async def get_file_sha(token: str, owner: str, repo_name: str, path: str) -> str | None:
    """Return the blob SHA of a file, or None if it doesn't exist."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/contents/{path}",
            headers=_auth_headers(token),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json().get("sha")


async def push_file(
    token: str,
    owner: str,
    repo_name: str,
    path: str,
    content: str | bytes,
    retries: int = 3,
    retry_delay: float = 3.0,
) -> None:
    """Create or update a single file in the repo.

    Retries on 404 to handle the brief window after repo creation where
    GitHub's contents API isn't fully ready yet.
    """
    if isinstance(content, str):
        content = content.encode()
    encoded = base64.b64encode(content).decode()

    for attempt in range(retries):
        sha = await get_file_sha(token, owner, repo_name, path)
        body: dict = {"message": f"Update {path}", "content": encoded}
        if sha:
            body["sha"] = sha

        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/contents/{path}",
                headers=_auth_headers(token),
                json=body,
            )
            if response.status_code == 404 and attempt < retries - 1:
                logger.warning("push_file 404 for %s/%s/%s, retrying in %.0fs...", owner, repo_name, path, retry_delay)
                await asyncio.sleep(retry_delay)
                continue
            response.raise_for_status()
            return


async def push_files(
    token: str,
    owner: str,
    repo_name: str,
    files: dict[str, str | bytes],
) -> None:
    """Push multiple files to the repo sequentially."""
    for path, content in files.items():
        await push_file(token, owner, repo_name, path, content)


async def enable_pages(token: str, owner: str, repo_name: str) -> None:
    """Enable GitHub Pages on the main branch root."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/pages",
            headers=_auth_headers(token),
            json={"source": {"branch": "main", "path": "/"}},
        )
        # 201 = created, 409 = already enabled — both are fine
        if response.status_code not in (201, 409):
            response.raise_for_status()


def get_pages_url(owner: str, repo_name: str) -> str:
    """Return the expected GitHub Pages URL."""
    return f"https://{owner}.github.io/{repo_name}"


async def set_custom_domain(token: str, owner: str, repo_name: str, domain: str) -> None:
    """Push a CNAME file and register the custom domain via the Pages API."""
    await push_file(token, owner, repo_name, "CNAME", domain)
    async with httpx.AsyncClient() as client:
        response = await client.put(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/pages",
            headers=_auth_headers(token),
            json={"cname": domain},
        )
        if response.status_code not in (200, 204):
            response.raise_for_status()


async def delete_repo(token: str, owner: str, repo_name: str) -> None:
    """Delete a repo. Used for test teardown."""
    async with httpx.AsyncClient() as client:
        response = await client.delete(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}",
            headers=_auth_headers(token),
        )
        response.raise_for_status()
