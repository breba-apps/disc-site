"""
Clear GitHub credentials for a user.
Usage: uv run python scripts/disconnect_github.py <username>
"""
import asyncio
import sys

from breba_app.config import init_db, load_env
from breba_app.models.user import User


async def main(username: str):
    load_env()
    await init_db()

    user = await User.find_one(User.username == username)
    if not user:
        print(f"User '{username}' not found.")
        sys.exit(1)

    user.github_access_token = None
    user.github_username = None
    await user.save()
    print(f"GitHub credentials cleared for '{username}'.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run python scripts/disconnect_github.py <username>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
