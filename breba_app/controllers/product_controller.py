from beanie import PydanticObjectId
from beanie.odm.operators.update.general import Set
from motor.motor_asyncio import AsyncIOMotorClient

from breba_app.models.deployment import Deployment
from breba_app.models.product import Product
from breba_app.storage import delete_product_files, delete_uploaded_sites


async def delete_product_and_deployments(user_id: str, product_id: str):
    client: AsyncIOMotorClient = Product.get_motor_collection().database.client  # type: ignore

    async with await client.start_session() as session:
        async with session.start_transaction():
            product: Product | None = await Product.find_one(
                Product.product_id == product_id,
                Product.user.id == PydanticObjectId(user_id),
                session=session,
            )

            if not product:
                raise ValueError(f"Product not found: {product_id} for user {user_id}")

            await Deployment.find(
                Deployment.product.id == product.id,
                session=session,
            ).delete_many()

            await product.delete(session=session)

            return True


async def get_deployments_for(product_id: str):
    product = await Product.find_one(Product.product_id == product_id)
    if not product:
        raise ValueError(f"Product not found: {product_id}")
    # This will lookup using DBRef id similar to: {"product.$id": ObjectId("abcdefg")}
    deployments = await Deployment.find(Deployment.product.id == product.id).to_list()
    return deployments


async def delete_product(user_id: str, product_id: str):
    # Get the list of deployments before we delete them from DB
    deployments = await get_deployments_for(product_id)
    site_names = [deployment.deployment_id for deployment in deployments]

    # Frist delete the mongodb data, because that will make the UI look like it was deleted
    await delete_product_and_deployments(user_id, product_id)

    # If mongoDB is cleared, delete the s3 data. This is more error-prone, but less user impact
    if site_names:
        await delete_uploaded_sites(site_names)
    await delete_product_files(user_id, product_id)


async def rename_product(user_id: str, product_id: str, new_name: str):
    product: Product | None = await Product.find_one(
        Product.product_id == product_id,
        Product.user.id == PydanticObjectId(user_id),
    )

    if not product:
        raise ValueError(f"Product not found: {product_id} for user {user_id}")

    await product.update(Set({Product.name: new_name}))


