import logging

from beanie import PydanticObjectId

from breba_app.builder import build
from breba_app.models.deployment import Deployment
from breba_app.models.product import Product
from breba_app.models.user import User
from breba_app.storage import upload_site, read_all_files_in_memory

logger = logging.getLogger(__name__)


async def run_deployment(user_id: str, product: Product, deployment_id: str) -> str:
    # TODO: optimize this. User should be fully stored in session at login
    # TODO: optimize this. Product_id should come with the request from the forntend
    #  (in fact this is a bug that product is stored in session). The internal id should be mapped on the backend
    try:
        user = await User.get(PydanticObjectId(user_id))
        deployment = await Deployment.get_or_create(deployment_id, product.id, user.id)
        source = await read_all_files_in_memory(user_id, product.product_id)
        built = build(source)
        url = await upload_site(built, deployment.deployment_id)
        logger.info(f"User: {user_id}, Product: {product.product_id}, uploaded site to url: {url}")

        await deployment.update_deployment_timestamp()
        return f"Deployed your website to: {url}"
    except ValueError as e:
        message = str(e)
        logging.exception(message)
        return message
    except Exception as e:
        message = f"Could not deploy to {deployment_id}. Please try again later."
        logging.exception(message)
        return message
