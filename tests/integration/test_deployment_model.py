import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from breba_app.config import load_env
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
    mongo_uri = os.getenv("MONGO_URI")
    client = AsyncIOMotorClient(mongo_uri)
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
async def mock_product(init_test_db, mock_user):
    product = Product(
        product_id=str(uuid.uuid4()),
        name=f"Test Product {uuid.uuid4().hex[:8]}",
        user=mock_user
    )
    await product.save()
    yield product
    await product.delete()


@pytest.mark.asyncio
async def test_concurrent_get_or_create_same_deployment(mock_user, mock_product):
    deployment_id = f"test-deployment-{uuid.uuid4().hex[:8]}"

    async def create_deployment():
        return await Deployment.get_or_create(deployment_id, mock_product.id, mock_user.id)

    tasks = [create_deployment() for _ in range(10)]
    deployments = await asyncio.gather(*tasks)

    assert all(d.deployment_id == deployment_id for d in deployments)
    assert all(d.user.ref.id == mock_user.id for d in deployments)
    assert all(d.product.ref.id == mock_product.id for d in deployments)

    db_deployments = await Deployment.find(Deployment.deployment_id == deployment_id).to_list()
    assert len(db_deployments) == 1
    await db_deployments[0].delete()


@pytest.mark.asyncio
async def test_concurrent_get_or_create_different_users(mock_product):
    users = []
    for i in range(3):
        user_id = str(uuid.uuid4())
        user = User(
            username=f"testuser_{user_id}",
            password_hash="hashed_password"
        )
        await user.save()
        users.append(user)

    deployment_id = f"test-deployment-{uuid.uuid4().hex[:8]}"

    async def create_deployment_for_user(user):
        try:
            return await Deployment.get_or_create(deployment_id, mock_product.id, user.id)
        except ValueError as e:
            return e

    tasks = [create_deployment_for_user(user) for user in users]
    results = await asyncio.gather(*tasks)

    successful = [r for r in results if isinstance(r, Deployment)]
    errors = [r for r in results if isinstance(r, ValueError)]

    assert len(successful) == 1
    assert len(errors) == 2
    for e in errors:
        assert "belongs to a different user" in str(e)

    for user in users:
        await user.delete()

    if successful:
        await successful[0].delete()


@pytest.mark.asyncio
async def test_concurrent_get_or_create_ownership_conflict(init_test_db):
    user1 = User(
        username=f"user1_{uuid.uuid4().hex[:8]}",
        password_hash="hashed_password"
    )
    await user1.save()

    user2 = User(
        username=f"user2_{uuid.uuid4().hex[:8]}",
        password_hash="hashed_password"
    )
    await user2.save()

    product1 = Product(
        product_id=str(uuid.uuid4()),
        name=f"Product 1 {uuid.uuid4().hex[:8]}",
        user=user1
    )
    await product1.save()

    product2 = Product(
        product_id=str(uuid.uuid4()),
        name=f"Product 2 {uuid.uuid4().hex[:8]}",
        user=user2
    )
    await product2.save()

    deployment_id = f"test-deployment-{uuid.uuid4().hex[:8]}"

    deployment1 = await Deployment.get_or_create(deployment_id, product1.id, user1.id)

    with pytest.raises(ValueError, match="exists but belongs to a different user"):
        await Deployment.get_or_create(deployment_id, product2.id, user2.id)

    await deployment1.delete()
    await product1.delete()
    await product2.delete()
    await user1.delete()
    await user2.delete()
