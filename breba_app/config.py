import os
from pathlib import Path

from beanie import init_beanie
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

from breba_app.models.deployment import Deployment
from breba_app.models.product import Product
from breba_app.models.user import User

DOT_ENV_PATH = Path(".secrets/breba/")
SPEC_FILE_NAME = "spec.txt"
INDEX_FILE_NAME = "index.html"


def load_env(file: str | None = None):
    file = file or ".env"
    working_dir = Path(".").resolve()

    # try going up the directory tree until we find .secrets directory
    while not (working_dir / DOT_ENV_PATH).exists():
        working_dir = working_dir.parent
        if working_dir == Path("/"):
            raise FileNotFoundError(".secrets directory not found")

    load_dotenv(working_dir / DOT_ENV_PATH / file)


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
