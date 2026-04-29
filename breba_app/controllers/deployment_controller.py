import logging

from beanie import PydanticObjectId

from breba_app.models.deployment import Deployment
from breba_app.models.product import Product
from breba_app.models.user import User
from breba_app.storage import upload_site

logger = logging.getLogger(__name__)


async def run_deployment(user_id: str, product: Product, deployment_id: str) -> str:
    try:
        user = await User.get(PydanticObjectId(user_id))
        deployment = await Deployment.get_or_create(deployment_id, product.id, user.id)
        url = await upload_site(user_id, product.product_id, deployment.deployment_id)
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
