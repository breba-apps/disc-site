import logging
import os
from pathlib import Path

from beanie import init_beanie
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

from breba_app.models.deployment import Deployment
from breba_app.models.product import Product
from breba_app.models.user import User

logger = logging.getLogger(__name__)

DOT_ENV_PATH = Path(".secrets/breba/")
SPEC_FILE_NAME = "spec.txt"
INDEX_FILE_NAME = "index.html"

def _read_required_env_keys() -> list[str]:
    env_example = Path(__file__).parent / "env.example"
    keys = []
    for line in env_example.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.append(line.split("=", 1)[0].strip())
    logger.debug("load_env: required keys read from env.example: %s", keys)
    return keys


_REQUIRED_ENV_KEYS = _read_required_env_keys()


def load_env(file: str | None = None):
    file = file or ".env"
    if all(os.getenv(key) for key in _REQUIRED_ENV_KEYS):
        logger.info("load_env: all required env vars already set in environment, skipping .env lookup")
        return
    else:
        logger.info(f"load_env: some required env vars not set in environment, loading {file}")
        logger.info(f"missing keys: {[set(_REQUIRED_ENV_KEYS) - set(os.environ.keys())]}")

    working_dir = Path(".").resolve()

    # try going up the directory tree until we find .secrets directory
    while not (working_dir / DOT_ENV_PATH).exists():
        working_dir = working_dir.parent
        if working_dir == Path("/"):
            raise FileNotFoundError(".secrets directory not found")

    env_path = working_dir / DOT_ENV_PATH / file
    logger.info("load_env: loading env vars from %s", env_path)
    load_dotenv(env_path)


async def init_db():
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        raise ValueError("MONGO_URI not found in environment variables. Make sure to run load_env() first.")
    client = AsyncIOMotorClient(mongo_uri)
    db = client.get_database('breba')

    User.model_rebuild(_types_namespace={"Product": Product})
    Product.model_rebuild(_types_namespace={"User": User, "Deployment": Deployment})
    Deployment.model_rebuild(_types_namespace={"Product": Product})

    await init_beanie(database=db, document_models=[User, Product, Deployment])
