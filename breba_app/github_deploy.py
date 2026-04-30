import asyncio
import base64
import logging
import re
from typing import Any

import httpx

GITHUB_API_BASE = "https://api.github.com"
GITHUB_GRAPHQL_API = "https://api.github.com/graphql"

logger = logging.getLogger(__name__)


def _auth_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


class GitHubGraphQLError(RuntimeError):
    pass


def _to_base64_content(content: str | bytes) -> str:
    if isinstance(content, str):
        raw = content.encode("utf-8")
    else:
        raw = content
    return base64.b64encode(raw).decode("ascii")


async def _graphql(
    client: httpx.AsyncClient,
    token: str,
    query: str,
    variables: dict[str, Any],
) -> dict[str, Any]:
    response = await client.post(
        GITHUB_GRAPHQL_API,
        headers=_auth_headers(token),
        json={"query": query, "variables": variables},
    )
    response.raise_for_status()
    payload = response.json()
    if "errors" in payload and payload["errors"]:
        raise GitHubGraphQLError(str(payload["errors"]))
    return payload["data"]


_GET_BRANCH_HEAD_OID_QUERY = """
query GetBranchHeadOid($owner: String!, $repo: String!, $branch: String!) {
  repository(owner: $owner, name: $repo) {
    ref(qualifiedName: $branch) {
      target {
        __typename
        ... on Commit {
          oid
        }
      }
    }
  }
}
"""

_CREATE_COMMIT_ON_BRANCH_MUTATION = """
mutation CreateCommitOnBranch($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) {
    commit {
      oid
      url
    }
  }
}
"""


async def _get_branch_head_oid(
    client: httpx.AsyncClient,
    token: str,
    owner: str,
    repo_name: str,
    branch: str,
) -> str:
    data = await _graphql(
        client=client,
        token=token,
        query=_GET_BRANCH_HEAD_OID_QUERY,
        variables={"owner": owner, "repo": repo_name, "branch": f"refs/heads/{branch}"},
    )
    repository = data.get("repository")
    if not repository:
        raise GitHubGraphQLError(f"Repository not found: {owner}/{repo_name}")
    ref = repository.get("ref")
    if not ref:
        raise GitHubGraphQLError(f"Branch not found: refs/heads/{branch} in {owner}/{repo_name}")
    target = ref.get("target")
    if not target or target.get("__typename") != "Commit":
        raise GitHubGraphQLError(f"Branch target is not a commit in {owner}/{repo_name}")
    oid = target.get("oid")
    if not oid:
        raise GitHubGraphQLError(f"Missing HEAD oid for {branch} in {owner}/{repo_name}")
    return oid


def slugify(name: str) -> str:
    """Convert a product name to a valid GitHub repo name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "breba-page"


async def create_repo(token: str, org: str, repo_name: str) -> dict:
    """Create a new public repo under an org, or return the existing one if the name is taken.
    Returns repo info with 'name', 'full_name', 'html_url'.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GITHUB_API_BASE}/orgs/{org}/repos",
            headers=_auth_headers(token),
            json={"name": repo_name, "private": False, "auto_init": True},
        )
        if response.status_code == 201:
            return response.json()
        if response.status_code == 422:
            # Repo already exists — fetch and return it
            get_response = await client.get(
                f"{GITHUB_API_BASE}/repos/{org}/{repo_name}",
                headers=_auth_headers(token),
            )
            get_response.raise_for_status()
            return get_response.json()
        response.raise_for_status()


async def push_files(
    token: str,
    owner: str,
    repo_name: str,
    files: dict[str, str | bytes],
    *,
    branch: str = "main",
    commit_headline: str = "Update files",
    files_to_delete: list[str] | None = None,
    expected_head_oid: str | None = None,
    retries: int = 3,
    retry_delay: float = 2.0,
) -> dict[str, str]:
    """Push files to the repo in a single atomic commit via the GraphQL API.

    Returns {"commit_oid": ..., "commit_url": ..., "branch": ...}.
    """
    if not files and not files_to_delete:
        raise ValueError("files must not be empty")

    additions = [
        {"path": path, "contents": _to_base64_content(content)}
        for path, content in files.items()
    ]
    deletions = [{"path": path} for path in (files_to_delete or [])]

    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(retries):
            current_head_oid = expected_head_oid or await _get_branch_head_oid(
                client, token, owner, repo_name, branch
            )

            file_changes: dict[str, Any] = {}
            if additions:
                file_changes["additions"] = additions
            if deletions:
                file_changes["deletions"] = deletions

            input_payload: dict[str, Any] = {
                "branch": {
                    "repositoryNameWithOwner": f"{owner}/{repo_name}",
                    "branchName": branch,
                },
                "message": {"headline": commit_headline},
                "expectedHeadOid": current_head_oid,
                "fileChanges": file_changes,
            }

            try:
                data = await _graphql(
                    client=client,
                    token=token,
                    query=_CREATE_COMMIT_ON_BRANCH_MUTATION,
                    variables={"input": input_payload},
                )
                commit = data["createCommitOnBranch"]["commit"]
                return {"commit_oid": commit["oid"], "commit_url": commit["url"], "branch": branch}

            except GitHubGraphQLError as exc:
                message = str(exc)
                should_retry = attempt < retries - 1 and (
                    "expectedHeadOid" in message
                    or "was at" in message
                    or "Head branch was modified" in message
                    or "ref" in message
                )
                if should_retry:
                    logger.warning(
                        "GraphQL commit race for %s/%s on %s, retrying in %.1fs...",
                        owner, repo_name, branch, retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    expected_head_oid = None
                    continue
                raise


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
    await push_files(token, owner, repo_name, {"CNAME": domain}, commit_headline="Set custom domain")
    async with httpx.AsyncClient() as client:
        response = await client.put(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/pages",
            headers=_auth_headers(token),
            json={"cname": domain},
        )
        if response.status_code not in (200, 204):
            response.raise_for_status()


async def enforce_https(token: str, owner: str, repo_name: str) -> None:
    """Enable HTTPS enforcement on a GitHub Pages site. Requires the SSL cert to already exist."""
    async with httpx.AsyncClient() as client:
        response = await client.put(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/pages",
            headers=_auth_headers(token),
            json={"https_enforced": True},
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
