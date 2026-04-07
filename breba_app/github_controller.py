import logging
from dataclasses import dataclass

from breba_app.github_oauth import exchange_code_for_token, get_github_username, verify_state
from breba_app.models.user import User

logger = logging.getLogger(__name__)


@dataclass
class GitHubCallbackResult:
    success: bool
    github_username: str | None = None
    error: str | None = None


@dataclass
class GitHubStatusResult:
    connected: bool
    github_username: str | None


async def connect_github_to_user(username: str, access_token: str, github_username: str) -> None:
    """Save github_access_token and github_username to the User document."""
    user = await User.find_one(User.username == username)
    if not user:
        raise ValueError(f"User not found: {username}")
    user.github_access_token = access_token
    user.github_username = github_username
    await user.save()


async def handle_github_callback(
    code: str,
    state: str,
    secret: str,
    client_id: str,
    client_secret: str,
) -> GitHubCallbackResult:
    """Verify state, exchange code, fetch GitHub username, persist to DB."""
    username = verify_state(state, secret)
    if username is None:
        return GitHubCallbackResult(success=False, error="Invalid or expired state. Please try again.")

    try:
        access_token = await exchange_code_for_token(client_id, client_secret, code)
        gh_username = await get_github_username(access_token)
        await connect_github_to_user(username, access_token, gh_username)
        return GitHubCallbackResult(success=True, github_username=gh_username)
    except Exception as exc:
        logger.error("GitHub OAuth callback error for user %s: %s", username, exc)
        return GitHubCallbackResult(success=False, error=str(exc))


async def get_github_connection_status(username: str) -> GitHubStatusResult:
    """Return whether the user has a connected GitHub account."""
    user = await User.find_one(User.username == username)
    if user is None:
        return GitHubStatusResult(connected=False, github_username=None)
    return GitHubStatusResult(
        connected=user.github_access_token is not None,
        github_username=user.github_username,
    )
