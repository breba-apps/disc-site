import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from breba_app.config import load_env
from breba_app.github_controller import connect_github_to_user
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
