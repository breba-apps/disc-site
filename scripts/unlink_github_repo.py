"""
Clear the GitHub repo link for a product so the next deploy picks the correct repo.
Usage: uv run python scripts/unlink_github_repo.py
"""
import asyncio
import sys

from beanie.operators import Set

from breba_app.config import init_db, load_env
from breba_app.models.product import Product
from breba_app.models.user import User


async def main():
    load_env()
    await init_db()

    username = input("Username: ").strip()
    user = await User.find_one(User.username == username)
    if not user:
        print(f"User '{username}' not found.")
        sys.exit(1)

    products = await Product.find(Product.user.id == user.id).to_list()
    if not products:
        print(f"No products found for '{username}'.")
        sys.exit(1)

    print("Products:")
    for p in products:
        repo = p.github_repo or "(none)"
        print(f"  {p.name or '(unnamed)'}  —  repo: {repo}  —  id: {p.product_id}")

    product_name = input("Product name: ").strip()
    product = next((p for p in products if p.name == product_name), None)
    if not product:
        print(f"Product '{product_name}' not found for user '{username}'.")
        sys.exit(1)

    if not product.github_repo:
        print(f"Product '{product_name}' has no GitHub repo linked.")
        sys.exit(0)

    old_repo = product.github_repo
    await product.update(Set({Product.github_repo: None}))
    print(f"Unlinked '{old_repo}' from product '{product_name}'. Next deploy will use the product name to find or create the repo.")


if __name__ == "__main__":
    asyncio.run(main())
