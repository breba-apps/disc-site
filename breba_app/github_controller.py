import logging
from dataclasses import dataclass

from beanie.odm.operators.update.general import Set

from breba_app.github_deploy import (
    create_repo,
    enable_pages,
    get_pages_url,
    push_files,
    slugify,
)
from breba_app.github_oauth import exchange_code_for_token, get_github_username, verify_state
from breba_app.models.product import Product
from breba_app.models.user import User
from breba_app.storage import read_all_files_in_memory

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


@dataclass
class GitHubDeployResult:
    success: bool
    pages_url: str | None = None
    repo_url: str | None = None
    error: str | None = None


async def deploy_to_github(username: str, product_id: str) -> GitHubDeployResult:
    """Deploy product files to GitHub Pages under the user's account."""
    user = await User.find_one(User.username == username)
    if not user or not user.github_access_token:
        return GitHubDeployResult(success=False, error="GitHub account not connected.")

    product = await Product.find_one(Product.product_id == product_id)
    if not product:
        return GitHubDeployResult(success=False, error=f"Product not found: {product_id}")

    token = user.github_access_token
    owner = user.github_username

    try:
        file_store = await read_all_files_in_memory(username, product_id)
        files = {
            path: fw.content
            for path, fw in file_store._files.items()
        }

        if product.github_repo:
            # Re-deploy: push updated files to existing repo
            repo_name = product.github_repo.split("/", 1)[1]
        else:
            # First deploy: create repo
            repo_name = slugify(product.name or "breba-page")
            repo_info = await create_repo(token, repo_name)
            repo_name = repo_info["name"]  # may have been suffixed for uniqueness
            await enable_pages(token, owner, repo_name)
            await product.update(Set({Product.github_repo: f"{owner}/{repo_name}"}))

        await push_files(token, owner, repo_name, files)

        pages_url = get_pages_url(owner, repo_name)
        repo_url = f"https://github.com/{owner}/{repo_name}"
        return GitHubDeployResult(success=True, pages_url=pages_url, repo_url=repo_url)

    except Exception as exc:
        logger.error("GitHub deploy error for user %s product %s: %s", username, product_id, exc)
        return GitHubDeployResult(success=False, error=str(exc))


async def get_github_connection_status(username: str) -> GitHubStatusResult:
    """Return whether the user has a connected GitHub account."""
    user = await User.find_one(User.username == username)
    if user is None:
        return GitHubStatusResult(connected=False, github_username=None)
    return GitHubStatusResult(
        connected=user.github_access_token is not None,
        github_username=user.github_username,
    )
