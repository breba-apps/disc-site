import datetime
from typing import List
from uuid import uuid4

from beanie import Document, Link, BackLink
from beanie.odm.operators.update.general import Set
from pydantic import Field

from .user import User


class Product(Document):
    product_id: str = Field(default_factory=lambda: uuid4().hex)
    name: str | None = None
    executive_summary: str | None = None
    user: Link[User]
    active: bool = False
    cost: float = 0
    github_repo: str | None = None  # "owner/repo-name" once deployed to GitHub
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))

    # Back-reference to deployments
    deployments: List[BackLink["Deployment"]] | None = Field(
        default_factory=list,
        original_field="product"
    )

    class Settings:
        name = "products"

    async def increment_cost(self, amount: float):
        """Atomically increment the product's cost"""
        await self.inc({Product.cost: amount})


async def create_blank_product_for(user_name: str, product_name: str, active: bool):
    user_obj = await User.find_one(User.username == user_name)

    # Clear all active products
    await Product.find(Product.user.id == user_obj.id, Product.active == True).update(
        Set({Product.active: False})
    )

    product = Product(user=user_obj, name=product_name, active=active)
    await product.insert()
    return product


async def set_product_active(user_name: str, product_id: str):
    user_obj = await User.find_one(User.username == user_name)

    # Clear all active products
    await Product.find(Product.user.id == user_obj.id, Product.active == True).update(
        Set({Product.active: False})
    )

    product = await Product.find_one(Product.product_id == product_id)
    await product.update(Set({Product.active: True}))


async def create_or_update_product_for(user_name: str, product_id: str | None = None, product_name: str | None = None):
    user_obj = await User.find_one(User.username == user_name, fetch_links=False)

    # Clear all active products
    await Product.find(Product.user.id == user_obj.id, Product.active == True).update(
        Set({Product.active: False})
    )

    # Insert new active product
    product = Product(product_id=product_id, user=user_obj, name=product_name, active=True)
    await Product.find_one(Product.product_id == product_id).upsert(
        Set({
            Product.name: product_name,
            Product.active: True
        }),
        on_insert=product
    )
    return product
