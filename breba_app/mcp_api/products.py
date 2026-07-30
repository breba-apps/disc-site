"""Owned-product listing shared by the consent page and ``/mcp/products``.

``/mcp/products`` promises the same list the user already sees on the consent
page; keeping the query and the {"id", "name"} projection here makes that
contract structural instead of two copies kept in sync by hand.
"""
from beanie import PydanticObjectId

from breba_app.models.product import Product


async def owned_products(user_oid: PydanticObjectId) -> list[Product]:
    return await Product.find(Product.user.id == user_oid).to_list()


def product_listing(products: list[Product]) -> list[dict]:
    """{"id", "name"} entries; a product with no name falls back to its id."""
    return [{"id": p.product_id, "name": p.name or p.product_id} for p in products]
