import pytest

from breba_app.github_oauth import (
    build_github_auth_url,
    generate_state,
    verify_state,
    exchange_code_for_token,
    get_github_username,
)


def test_build_github_auth_url():
    url = build_github_auth_url(client_id="my_client_id", state="my_state")
    assert "client_id=my_client_id" in url
    assert "scope=repo" in url
    assert "state=my_state" in url
    assert url.startswith("https://github.com/login/oauth/authorize")


def test_generate_and_verify_state():
    secret = "supersecret"
    username = "alice"
    state = generate_state(username, secret)
    result = verify_state(state, secret)
    assert result == username


def test_verify_state_invalid_signature():
    secret = "supersecret"
    state = generate_state("alice", secret)
    # Tamper with the signature
    payload_b64, sig = state.split(".", 1)
    tampered = f"{payload_b64}.{'0' * len(sig)}"
    result = verify_state(tampered, secret)
    assert result is None


def test_verify_state_invalid_format():
    result = verify_state("this-is-not-a-valid-state-token", "secret")
    assert result is None


@pytest.mark.asyncio
async def test_exchange_code_for_token_success(mocker):
    mock_response = mocker.MagicMock()
    mock_response.json.return_value = {"access_token": "ghs_abc123", "token_type": "bearer"}
    mock_response.raise_for_status = mocker.MagicMock()

    mock_client = mocker.AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

    mocker.patch("breba_app.github_oauth.httpx.AsyncClient", return_value=mock_client)

    token = await exchange_code_for_token("client_id", "client_secret", "code123")
    assert token == "ghs_abc123"


@pytest.mark.asyncio
async def test_exchange_code_for_token_error(mocker):
    mock_response = mocker.MagicMock()
    mock_response.json.return_value = {
        "error": "bad_verification_code",
        "error_description": "The code passed is incorrect or expired.",
    }
    mock_response.raise_for_status = mocker.MagicMock()

    mock_client = mocker.AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

    mocker.patch("breba_app.github_oauth.httpx.AsyncClient", return_value=mock_client)

    with pytest.raises(ValueError, match="GitHub OAuth error"):
        await exchange_code_for_token("client_id", "client_secret", "bad_code")


@pytest.mark.asyncio
async def test_get_github_username(mocker):
    mock_response = mocker.MagicMock()
    mock_response.json.return_value = {"login": "octocat", "id": 1}
    mock_response.raise_for_status = mocker.MagicMock()

    mock_client = mocker.AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

    mocker.patch("breba_app.github_oauth.httpx.AsyncClient", return_value=mock_client)

    username = await get_github_username("ghs_token123")
    assert username == "octocat"
