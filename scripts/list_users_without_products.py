import asyncio

from breba_app.config import init_db, load_env
from breba_app.models.product import Product
from breba_app.models.user import User

load_env()


async def run():
    await init_db()

    users = await User.find_all().to_list()
    stale = []
    for user in users:
        count = await Product.find(Product.user.id == user.id).count()
        if count == 0:
            stale.append(user)

    if not stale:
        print("All users have at least one product.")
        return

    print(f"{'USERNAME':<40} {'ID'}")
    print("-" * 80)
    for user in stale:
        print(f"{user.username:<40} {user.id}")


asyncio.run(run())
