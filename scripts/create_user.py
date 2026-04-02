import asyncio
import getpass


from breba_app.auth import create_user
from breba_app.config import init_db, load_env

load_env()


async def run():
    await init_db()
    username = input("Username: ")
    password = getpass.getpass("Password: ")
    await create_user(username, password)


asyncio.run(run())
