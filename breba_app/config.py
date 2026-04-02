import os
from pathlib import Path

from beanie import init_beanie
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

from breba_app.models.deployment import Deployment
from breba_app.models.product import Product
from breba_app.models.user import User

DOT_ENV_PATH = Path("../../.secrets/breba/")

def load_env(file: str | None = None):
    file = file or ".env"
    load_dotenv(DOT_ENV_PATH / file)

load_env()

MONGO_URI = os.getenv("MONGO_URI")

SPEC_FILE_NAME = "spec.txt"
INDEX_FILE_NAME = "index.html"


async def init_db():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client.get_database('breba')

    User.model_rebuild(_types_namespace={"Product": Product})
    Product.model_rebuild(_types_namespace={"User": User, "Deployment": Deployment})
    Deployment.model_rebuild(_types_namespace={"Product": Product})

    await init_beanie(database=db, document_models=[User, Product, Deployment])
