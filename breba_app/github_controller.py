import logging
from dataclasses import dataclass

from beanie.odm.operators.update.general import Set

from breba_app.github_deploy import (
    create_repo,
    enable_pages,
    get_pages_url,
    push_files,
    set_custom_domain,
    slugify,
)
from breba_app.crypto import decrypt_token, encrypt_token
from breba_app.github_oauth import exchange_code_for_token, get_github_orgs, get_github_username, verify_state
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
    user.github_access_token = encrypt_token(access_token)
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


async def list_github_orgs(username: str) -> list[str]:
    """Return the list of GitHub org names for the connected user."""
    user = await User.find_one(User.username == username)
    if not user or not user.github_access_token:
        return []
    return await get_github_orgs(decrypt_token(user.github_access_token))


async def deploy_to_github(username: str, product_id: str, org: str | None = None) -> GitHubDeployResult:
    """Deploy product files to GitHub Pages under an org.

    On first deploy, `org` is required. It is stored on the product and reused on re-deploys.
    """
    user = await User.find_one(User.username == username)
    if not user or not user.github_access_token:
        return GitHubDeployResult(success=False, error="GitHub account not connected.")

    product = await Product.find_one(Product.product_id == product_id)
    if not product:
        return GitHubDeployResult(success=False, error=f"Product not found: {product_id}")

    token = decrypt_token(user.github_access_token)

    try:
        file_store = await read_all_files_in_memory(username, product_id)
        files = {path: fw.content for path, fw in file_store._files.items()}

        if product.github_repo:
            # Re-deploy: push updated files to existing repo
            deploy_org, repo_name = product.github_repo.split("/", 1)
            if product.custom_domain:
                files["CNAME"] = product.custom_domain
            await push_files(token, deploy_org, repo_name, files)
        else:
            # First deploy: org is required
            if not org:
                return GitHubDeployResult(success=False, error="An organization name is required for the first deploy.")
            repo_name = slugify(product.name or "breba-page")
            repo_info = await create_repo(token, org, repo_name)
            repo_name = repo_info["name"]  # may have been suffixed for uniqueness
            deploy_org = org
            # Push files before enabling Pages — Pages API requires content on the branch
            await push_files(token, deploy_org, repo_name, files)
            await enable_pages(token, deploy_org, repo_name)
            await product.update(Set({Product.github_repo: f"{deploy_org}/{repo_name}"}))


        pages_url = get_pages_url(deploy_org, repo_name)
        repo_url = f"https://github.com/{deploy_org}/{repo_name}"
        return GitHubDeployResult(success=True, pages_url=pages_url, repo_url=repo_url)

    except Exception as exc:
        logger.error("GitHub deploy error for user %s product %s: %s", username, product_id, exc)
        return GitHubDeployResult(success=False, error=str(exc))


@dataclass
class CustomDomainResult:
    success: bool
    error: str | None = None


async def set_github_custom_domain(username: str, product_id: str, domain: str) -> CustomDomainResult:
    """Push CNAME file and update Pages settings, then persist domain to the product."""
    user = await User.find_one(User.username == username)
    if not user or not user.github_access_token:
        return CustomDomainResult(success=False, error="GitHub account not connected.")

    product = await Product.find_one(Product.product_id == product_id)
    if not product or not product.github_repo:
        return CustomDomainResult(success=False, error="No GitHub repository found. Deploy first.")

    token = decrypt_token(user.github_access_token)
    org, repo_name = product.github_repo.split("/", 1)

    try:
        await set_custom_domain(token, org, repo_name, domain)
        await product.update(Set({Product.custom_domain: domain}))
        return CustomDomainResult(success=True)
    except Exception as exc:
        logger.error("Custom domain error for user %s product %s: %s", username, product_id, exc)
        return CustomDomainResult(success=False, error=str(exc))


async def get_github_connection_status(username: str) -> GitHubStatusResult:
    """Return whether the user has a connected GitHub account."""
    user = await User.find_one(User.username == username)
    if user is None:
        return GitHubStatusResult(connected=False, github_username=None)
    return GitHubStatusResult(
        connected=user.github_access_token is not None,
        github_username=user.github_username,
    )
