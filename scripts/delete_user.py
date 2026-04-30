"""
Delete a user and all their products and deployments from MongoDB.

Usage:
    uv run python scripts/delete_user.py <username>
"""
import asyncio
import sys

from breba_app.config import init_db, load_env
from breba_app.models.deployment import Deployment
from breba_app.models.product import Product
from breba_app.models.user import User
from bson import DBRef

load_env()


async def run(username: str):
    await init_db()

    user = await User.find_one(User.username == username)
    if not user:
        print(f"User not found: {username}")
        sys.exit(1)

    products = await Product.find(Product.user.id == user.id).to_list()

    print(f"User:     {user.username}  ({user.id})")
    print(f"Products: {len(products)}")

    total_deployments = 0
    for product in products:
        count = await Deployment.find(
            Deployment.product == DBRef("products", product.id)
        ).count()
        total_deployments += count
        print(f"  product {product.product_id!r}  ({count} deployment(s))")

    print()
    confirm = input(f"Delete user '{username}' and all {len(products)} product(s), {total_deployments} deployment(s)? [y/N] ")
    if confirm.strip().lower() != "y":
        print("Aborted.")
        return

    for product in products:
        await Deployment.find(
            Deployment.product == DBRef("products", product.id)
        ).delete_many()
        await product.delete()

    await user.delete()
    print(f"Deleted user '{username}' with {len(products)} product(s) and {total_deployments} deployment(s).")


if len(sys.argv) != 2:
    print("Usage: uv run python scripts/delete_user.py <username>")
    sys.exit(1)

asyncio.run(run(sys.argv[1]))
