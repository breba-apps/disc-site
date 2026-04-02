import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from breba_app.config import load_env
from breba_app.controllers.product_controller import delete_product_and_deployments
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


@pytest_asyncio.fixture
async def test_product(init_test_db, mock_user):
    product = Product(
        product_id=str(uuid.uuid4()),
        name=f"Test Product {uuid.uuid4().hex[:8]}",
        user=mock_user
    )
    await product.save()
    yield product
    await product.delete()


@pytest.mark.asyncio
async def test_delete_product(mock_user, test_product):
    # TODO: need to test actual delete_product function
    await delete_product_and_deployments(mock_user.username, test_product.product_id)

# This will delete a product that is not in the test db
# @pytest.mark.asyncio
# async def test_delete_product():
#     await init_db()
#     await delete_product("yason", "2ce1e6db2e7142efb39e329fdb7acf1a")