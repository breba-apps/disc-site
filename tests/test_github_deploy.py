import base64

import pytest

from breba_app.github_deploy import GitHubGraphQLError, get_pages_url, slugify


def _make_head_oid_response(mocker, oid: str):
    r = mocker.MagicMock()
    r.raise_for_status = mocker.MagicMock()
    r.json.return_value = {
        "data": {
            "repository": {
                "ref": {"target": {"__typename": "Commit", "oid": oid}}
            }
        }
    }
    return r


def _make_commit_response(mocker, oid: str = "newoid", url: str = "https://github.com/o/r/commit/newoid"):
    r = mocker.MagicMock()
    r.raise_for_status = mocker.MagicMock()
    r.json.return_value = {
        "data": {
            "createCommitOnBranch": {
                "commit": {"oid": oid, "url": url}
            }
        }
    }
    return r


def _make_error_response(mocker, message: str):
    r = mocker.MagicMock()
    r.raise_for_status = mocker.MagicMock()
    r.json.return_value = {"errors": [{"message": message}]}
    return r


def _mock_graphql_client(mocker, responses: list):
    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.post = mocker.AsyncMock(side_effect=responses)
    mocker.patch("breba_app.github_deploy.httpx.AsyncClient", return_value=mock_client)
    return mock_client


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

def test_slugify_simple():
    assert slugify("My Cool Site") == "my-cool-site"


def test_slugify_special_chars():
    assert slugify("Hello, World!") == "hello-world"


def test_slugify_multiple_hyphens():
    assert slugify("foo   bar") == "foo-bar"


def test_slugify_empty():
    assert slugify("") == "breba-page"


def test_slugify_only_special():
    assert slugify("!!!") == "breba-page"


# ---------------------------------------------------------------------------
# get_pages_url
# ---------------------------------------------------------------------------

def test_get_pages_url():
    assert get_pages_url("octocat", "my-repo") == "https://octocat.github.io/my-repo"


# ---------------------------------------------------------------------------
# create_repo (mocked httpx)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_repo_success(mocker):
    mock_response = mocker.MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {
        "name": "my-repo",
        "full_name": "acme-corp/my-repo",
        "html_url": "https://github.com/acme-corp/my-repo",
    }

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.post = mocker.AsyncMock(return_value=mock_response)
    mocker.patch("breba_app.github_deploy.httpx.AsyncClient", return_value=mock_client)

    from breba_app.github_deploy import create_repo
    result = await create_repo("token123", "acme-corp", "my-repo")
    assert result["name"] == "my-repo"
    assert result["full_name"] == "acme-corp/my-repo"
    assert "orgs/acme-corp/repos" in mock_client.post.call_args.args[0]


@pytest.mark.asyncio
async def test_create_repo_name_conflict_retries(mocker):
    conflict = mocker.MagicMock()
    conflict.status_code = 422

    success = mocker.MagicMock()
    success.status_code = 201
    success.json.return_value = {"name": "my-repo-1", "full_name": "acme-corp/my-repo-1", "html_url": ""}

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.post = mocker.AsyncMock(side_effect=[conflict, success])
    mocker.patch("breba_app.github_deploy.httpx.AsyncClient", return_value=mock_client)

    from breba_app.github_deploy import create_repo
    result = await create_repo("token123", "acme-corp", "my-repo")
    assert result["name"] == "my-repo-1"
    assert mock_client.post.call_count == 2


# ---------------------------------------------------------------------------
# push_files — unit tests (mocked httpx)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_push_files_all_files_in_single_commit(mocker):
    """All files land in a single GraphQL commit — exactly two POST calls total."""
    mock_client = _mock_graphql_client(mocker, [
        _make_head_oid_response(mocker, "abc123"),
        _make_commit_response(mocker, "newoid"),
    ])

    from breba_app.github_deploy import push_files
    result = await push_files(
        "token", "octocat", "my-repo",
        {"index.html": "<html></html>", "styles.css": "body {}"},
    )

    assert result == {"commit_oid": "newoid", "commit_url": "https://github.com/o/r/commit/newoid", "branch": "main"}
    # Exactly one head-OID query + one commit mutation — no per-file calls
    assert mock_client.post.call_count == 2

    commit_input = mock_client.post.call_args_list[1].kwargs["json"]["variables"]["input"]
    paths = {a["path"] for a in commit_input["fileChanges"]["additions"]}
    assert paths == {"index.html", "styles.css"}


@pytest.mark.asyncio
async def test_push_files_content_is_base64_encoded(mocker):
    _mock_graphql_client(mocker, [
        _make_head_oid_response(mocker, "abc123"),
        _make_commit_response(mocker),
    ])

    from breba_app.github_deploy import push_files
    await push_files("token", "octocat", "my-repo", {"index.html": "hello"})

    from breba_app.github_deploy import httpx
    commit_input = httpx.AsyncClient.return_value.post.call_args_list[1].kwargs["json"]["variables"]["input"]
    encoded = commit_input["fileChanges"]["additions"][0]["contents"]
    assert base64.b64decode(encoded).decode() == "hello"


@pytest.mark.asyncio
async def test_push_files_bytes_content(mocker):
    _mock_graphql_client(mocker, [
        _make_head_oid_response(mocker, "abc123"),
        _make_commit_response(mocker),
    ])

    from breba_app.github_deploy import push_files
    await push_files("token", "octocat", "my-repo", {"logo.png": b"\x89PNG\r\n"})

    from breba_app.github_deploy import httpx
    commit_input = httpx.AsyncClient.return_value.post.call_args_list[1].kwargs["json"]["variables"]["input"]
    encoded = commit_input["fileChanges"]["additions"][0]["contents"]
    assert base64.b64decode(encoded) == b"\x89PNG\r\n"


@pytest.mark.asyncio
async def test_push_files_with_deletions(mocker):
    mock_client = _mock_graphql_client(mocker, [
        _make_head_oid_response(mocker, "abc123"),
        _make_commit_response(mocker),
    ])

    from breba_app.github_deploy import push_files
    await push_files(
        "token", "octocat", "my-repo",
        {"index.html": "<html></html>"},
        files_to_delete=["old.html"],
    )

    commit_input = mock_client.post.call_args_list[1].kwargs["json"]["variables"]["input"]
    assert commit_input["fileChanges"]["deletions"] == [{"path": "old.html"}]
    assert len(commit_input["fileChanges"]["additions"]) == 1


@pytest.mark.asyncio
async def test_push_files_expected_head_oid_skips_query(mocker):
    """When expected_head_oid is supplied, the head-OID query is skipped."""
    mock_client = _mock_graphql_client(mocker, [
        _make_commit_response(mocker),
    ])

    from breba_app.github_deploy import push_files
    await push_files(
        "token", "octocat", "my-repo",
        {"index.html": "hi"},
        expected_head_oid="preknown_oid",
    )

    assert mock_client.post.call_count == 1
    commit_input = mock_client.post.call_args_list[0].kwargs["json"]["variables"]["input"]
    assert commit_input["expectedHeadOid"] == "preknown_oid"


@pytest.mark.asyncio
async def test_push_files_retries_on_head_oid_conflict(mocker):
    """A race on expectedHeadOid triggers a retry with a freshly fetched OID."""
    mocker.patch("breba_app.github_deploy.asyncio.sleep")

    mock_client = _mock_graphql_client(mocker, [
        _make_head_oid_response(mocker, "stale_oid"),        # first head query
        _make_error_response(mocker, "expectedHeadOid was at stale_oid"),  # commit fails
        _make_head_oid_response(mocker, "fresh_oid"),        # retry head query
        _make_commit_response(mocker, "retried_oid"),        # commit succeeds
    ])

    from breba_app.github_deploy import push_files
    result = await push_files(
        "token", "octocat", "my-repo",
        {"index.html": "hi"},
        retries=3, retry_delay=0.0,
    )

    assert result["commit_oid"] == "retried_oid"
    assert mock_client.post.call_count == 4

    # Second attempt used the fresh OID
    second_commit_input = mock_client.post.call_args_list[3].kwargs["json"]["variables"]["input"]
    assert second_commit_input["expectedHeadOid"] == "fresh_oid"


@pytest.mark.asyncio
async def test_push_files_raises_on_non_retryable_error(mocker):
    """Errors unrelated to head-OID race are not retried."""
    _mock_graphql_client(mocker, [
        _make_head_oid_response(mocker, "abc123"),
        _make_error_response(mocker, "Repository not found"),
    ])

    from breba_app.github_deploy import push_files
    with pytest.raises(GitHubGraphQLError, match="Repository not found"):
        await push_files("token", "octocat", "my-repo", {"index.html": "hi"}, retries=3)


@pytest.mark.asyncio
async def test_push_files_raises_after_max_retries(mocker):
    """Retryable error exhausts all attempts and then raises."""
    mocker.patch("breba_app.github_deploy.asyncio.sleep")

    responses = []
    for _ in range(3):
        responses.append(_make_head_oid_response(mocker, "stale_oid"))
        responses.append(_make_error_response(mocker, "expectedHeadOid mismatch"))

    _mock_graphql_client(mocker, responses)

    from breba_app.github_deploy import push_files
    with pytest.raises(GitHubGraphQLError):
        await push_files("token", "octocat", "my-repo", {"index.html": "hi"}, retries=3, retry_delay=0.0)


@pytest.mark.asyncio
async def test_push_files_empty_raises():
    from breba_app.github_deploy import push_files
    with pytest.raises(ValueError):
        await push_files("token", "octocat", "my-repo", {})


@pytest.mark.asyncio
async def test_push_files_client_created_once(mocker):
    """The httpx client is created once per push_files call, not per retry."""
    mocker.patch("breba_app.github_deploy.asyncio.sleep")

    mock_client = _mock_graphql_client(mocker, [
        _make_head_oid_response(mocker, "s"),
        _make_error_response(mocker, "expectedHeadOid mismatch"),
        _make_head_oid_response(mocker, "f"),
        _make_commit_response(mocker),
    ])

    from breba_app.github_deploy import push_files, httpx
    await push_files("token", "octocat", "my-repo", {"f": "x"}, retries=3, retry_delay=0.0)

    assert httpx.AsyncClient.call_count == 1


# ---------------------------------------------------------------------------
# enable_pages (mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enable_pages_success(mocker):
    mock_response = mocker.MagicMock()
    mock_response.status_code = 201

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.post = mocker.AsyncMock(return_value=mock_response)
    mocker.patch("breba_app.github_deploy.httpx.AsyncClient", return_value=mock_client)

    from breba_app.github_deploy import enable_pages
    await enable_pages("token", "octocat", "my-repo")


@pytest.mark.asyncio
async def test_enable_pages_already_enabled(mocker):
    mock_response = mocker.MagicMock()
    mock_response.status_code = 409

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.post = mocker.AsyncMock(return_value=mock_response)
    mocker.patch("breba_app.github_deploy.httpx.AsyncClient", return_value=mock_client)

    from breba_app.github_deploy import enable_pages
    await enable_pages("token", "octocat", "my-repo")  # should not raise
