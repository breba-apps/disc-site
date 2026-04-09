import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from breba_app.config import load_env
from breba_app.github_controller import connect_github_to_user, deploy_to_github
from breba_app.github_deploy import delete_repo, get_pages_url
from breba_app.github_oauth import get_github_username
from breba_app.models.deployment import Deployment
from breba_app.models.product import Product
from breba_app.models.user import User


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def init_test_db():
    load_env(".env.integration_tests")
    MONGO_URI = os.getenv("MONGO_URI")
    client = AsyncIOMotorClient(MONGO_URI)
    db = client.get_database('breba-test')

    User.model_rebuild(_types_namespace={"Product": Product})
    Product.model_rebuild(_types_namespace={"User": User, "Deployment": Deployment})
    Deployment.model_rebuild(_types_namespace={"Product": Product})

    await init_beanie(database=db, document_models=[User, Product, Deployment])
    yield db
    await client.drop_database('breba_test')
    client.close()


@pytest_asyncio.fixture
async def mock_user(init_test_db):
    user_id = str(uuid.uuid4())
    user = User(
        username=f"testuser_{user_id}",
        password_hash="hashed_password"
    )
    await user.save()
    yield user
    await user.delete()


@pytest.mark.asyncio
async def test_connect_github_to_user(mock_user):
    await connect_github_to_user(mock_user.username, "ghs_token_abc", "octocat")

    updated = await User.find_one(User.username == mock_user.username)
    assert updated is not None
    assert updated.github_access_token == "ghs_token_abc"
    assert updated.github_username == "octocat"


@pytest.mark.asyncio
async def test_connect_github_to_user_updates_existing(mock_user):
    await connect_github_to_user(mock_user.username, "ghs_token_first", "octocat")
    await connect_github_to_user(mock_user.username, "ghs_token_second", "octocat2")

    updated = await User.find_one(User.username == mock_user.username)
    assert updated is not None
    assert updated.github_access_token == "ghs_token_second"
    assert updated.github_username == "octocat2"


@pytest.mark.asyncio
async def test_get_github_username_real_api():
    load_env(".env.integration_tests")
    token = os.getenv("GITHUB_TEST_TOKEN")
    if not token:
        pytest.skip("GITHUB_TEST_TOKEN not set in .env.integration_tests")

    github_username = await get_github_username(token)

    assert isinstance(github_username, str)
    assert len(github_username) > 0


@pytest.mark.asyncio
async def test_deploy_to_github_first_deploy(mock_user):
    load_env(".env.integration_tests")
    token = os.getenv("GITHUB_TEST_TOKEN")
    if not token:
        pytest.skip("GITHUB_TEST_TOKEN not set in .env.integration_tests")

    gh_username = await get_github_username(token)
    await connect_github_to_user(mock_user.username, token, gh_username)

    product = Product(
        product_id=uuid.uuid4().hex,
        name="Test Deploy Page",
        user=mock_user,
        active=True,
    )
    await product.save()

    # Patch read_all_files_in_memory to return a fake file store
    from unittest.mock import AsyncMock, MagicMock, patch
    from breba_app.filesystem.in_memory_store import InMemoryFileStore
    from breba_app.filesystem.models import FileWrite

    fake_store = InMemoryFileStore({
        "index.html": FileWrite(path="index.html", content=b"<html><body>Hello GitHub Pages</body></html>"),
    })
    with patch("breba_app.github_controller.read_all_files_in_memory", new=AsyncMock(return_value=fake_store)):
        result = await deploy_to_github(mock_user.username, product.product_id)

    # Cleanup: delete repo from GitHub
    if result.success and result.repo_url:
        repo_name = result.repo_url.split("/")[-1]
        try:
            await delete_repo(token, gh_username, repo_name)
        except Exception:
            pass

    await product.delete()

    assert result.success, result.error
    assert result.pages_url == get_pages_url(gh_username, "test-deploy-page")
    assert result.repo_url == f"https://github.com/{gh_username}/test-deploy-page"


@pytest.mark.asyncio
async def test_deploy_to_github_no_github_connected(mock_user):
    """Deploy fails gracefully when user has no GitHub token."""
    product = Product(
        product_id=uuid.uuid4().hex,
        name="Some Page",
        user=mock_user,
        active=True,
    )
    await product.save()

    result = await deploy_to_github(mock_user.username, product.product_id)

    await product.delete()

    assert not result.success
    assert "not connected" in result.error.lower()


@pytest.mark.asyncio
async def test_deploy_to_github_product_not_found(mock_user):
    await connect_github_to_user(mock_user.username, "fake_token", "octocat")
    result = await deploy_to_github(mock_user.username, "nonexistent_product_id")
    assert not result.success
    assert "not found" in result.error.lower()
