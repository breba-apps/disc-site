import pytest

from breba_app.github_deploy import get_pages_url, slugify


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
# get_file_sha (mocked httpx)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_file_sha_exists(mocker):
    mock_response = mocker.MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"sha": "abc123"}

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.get = mocker.AsyncMock(return_value=mock_response)
    mocker.patch("breba_app.github_deploy.httpx.AsyncClient", return_value=mock_client)

    from breba_app.github_deploy import get_file_sha
    sha = await get_file_sha("token", "octocat", "my-repo", "index.html")
    assert sha == "abc123"


@pytest.mark.asyncio
async def test_get_file_sha_not_found(mocker):
    mock_response = mocker.MagicMock()
    mock_response.status_code = 404

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.get = mocker.AsyncMock(return_value=mock_response)
    mocker.patch("breba_app.github_deploy.httpx.AsyncClient", return_value=mock_client)

    from breba_app.github_deploy import get_file_sha
    sha = await get_file_sha("token", "octocat", "my-repo", "index.html")
    assert sha is None


# ---------------------------------------------------------------------------
# push_file (mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_push_file_new(mocker):
    mocker.patch("breba_app.github_deploy.get_file_sha", return_value=None)

    mock_response = mocker.MagicMock()
    mock_response.raise_for_status = mocker.MagicMock()

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.put = mocker.AsyncMock(return_value=mock_response)
    mocker.patch("breba_app.github_deploy.httpx.AsyncClient", return_value=mock_client)

    from breba_app.github_deploy import push_file
    await push_file("token", "octocat", "my-repo", "index.html", "<html></html>")

    call_kwargs = mock_client.put.call_args.kwargs
    assert "sha" not in call_kwargs["json"]


@pytest.mark.asyncio
async def test_push_file_update_includes_sha(mocker):
    mocker.patch("breba_app.github_deploy.get_file_sha", return_value="existing_sha")

    mock_response = mocker.MagicMock()
    mock_response.raise_for_status = mocker.MagicMock()

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.put = mocker.AsyncMock(return_value=mock_response)
    mocker.patch("breba_app.github_deploy.httpx.AsyncClient", return_value=mock_client)

    from breba_app.github_deploy import push_file
    await push_file("token", "octocat", "my-repo", "index.html", "<html></html>")

    call_kwargs = mock_client.put.call_args.kwargs
    assert call_kwargs["json"]["sha"] == "existing_sha"


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
