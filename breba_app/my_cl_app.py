import asyncio

import chainlit as cl
from beanie import SortDirection, PydanticObjectId
from beanie.odm.operators.update.general import Set
from bson import DBRef
from chainlit import Message

from auth import verify_password
from storage import save_file_to_private, save_image_file_to_private, load_template, read_spec_text, \
    read_index_html, get_public_url
from deployment_controller import run_deployment
from llm_utils import get_product_name
from breba_app.models.deployment import Deployment
from breba_app.models.product import Product
from breba_app.models.user import User
from orchestrator import get_generator_response, to_builder, update_builder_spec, set_generator_response, to_generator

PRODUCT_NAME_PLACEHOLDER = "Unnamed Product"


# TODO: move this and others to storage module of some kind
async def has_cloud_storage(user_name: str, session_id: str):
    spec = read_spec_text(user_name, session_id)
    return spec is not None

async def populate_from_cloud_storage(user_name: str, session_id: str):
    spec = read_spec_text(user_name, session_id)
    product = read_index_html(user_name, session_id)
    set_generator_response(session_id, spec, product)

    await process_generator_message(product)

    await asyncio.gather(update_builder_spec(session_id, spec), builder_completed(spec),
                         process_generator_message("__completed__"))

async def create_blank_product_for(user_name: str):
    user_obj = await User.find_one(User.username == user_name)

    # Clear all active products
    await Product.find(Product.user.id == user_obj.id, Product.active == True).update(
        Set({Product.active: False})
    )

    product = Product(user=user_obj, name=PRODUCT_NAME_PLACEHOLDER, active=True)
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


async def create_or_update_product_for(user_name: str, product_id: str | None = None, product_spec: str = "",
                                       product_name: str | None = None):
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


async def builder_completed(payload: str):
    product_id = cl.user_session.get("product_id")
    user_name = cl.user_session.get("user").identifier
    product_name = cl.user_session.get("product_name")
    # The only time product_name is empty is when we are creating a new product
    if not product_name or product_name == PRODUCT_NAME_PLACEHOLDER:
        product_name = await get_product_name(payload)
        product = await create_or_update_product_for(user_name, product_id, payload, product_name)
        cl.user_session.set("product_name", product.name)

    save_file_to_private(user_name, product_id, "spec.txt", payload.encode("utf-8"), "text/plain")
    builder_message = {"method": "to_builder", "body": payload}
    await cl.send_window_message(builder_message)


async def generator_completed():
    product_id = cl.user_session.get("product_id")
    user_name = cl.user_session.get("user").identifier

    html = get_generator_response(product_id)

    save_file_to_private(user_name, product_id, "index.html", html, "text/html")

    await cl.Message(
        content="The website is ready to be deployed. Use the 🚀 from the sidebar to deploy your website").send()


async def process_generator_message(message: str):
    if message == "__completed__":
        await generator_completed()
    generator_message = {"method": "to_generator", "body": message}
    await cl.send_window_message(generator_message)


async def ask_user(message: str):
    await cl.Message(content=message).send()


async def update_deployments_list(product_id: PydanticObjectId):
    deployments = await Deployment.find(Deployment.product == DBRef("products", product_id)).sort(
        [("deployed_at", SortDirection.DESCENDING)]).to_list()

    if not deployments:
        return  # Nothing do here

    deployments_list = [{"id": str(deployment.id), "deployment_id": deployment.deployment_id,
                         "url": get_public_url(deployment.deployment_id)} for deployment in deployments]
    await cl.send_window_message({"method": "update_deployments_list", "body": deployments_list})


async def update_products_list(products: list[Product]):
    products_list = [{"product_id": product.product_id, "name": product.name, "active": product.active} for product in
                     products]
    await cl.send_window_message({"method": "update_products_list", "body": products_list})


@cl.on_chat_start
async def main():
    user_name = cl.user_session.get("user").identifier

    user = await User.find_one(User.username == user_name, fetch_links=True)

    active_product = None
    if user:
        await cl.send_window_message({"method": "logged_in"})
        async with cl.Step(name=f"Loading...", type="tool", ):
            # First try to get the active product
            active_product = await Product.find_one(
                Product.user.id == user.id, Product.active == True
            )

        # Fallback to most recently created product
        if not active_product:
            active_product = await Product.find(
                Product.user.id == user.id
            ).sort([("_id", SortDirection.DESCENDING)]).first_or_none()

        asyncio.create_task(update_products_list(user.products))

    if active_product:
        asyncio.create_task(update_deployments_list(active_product.id))

        has_storage = await has_cloud_storage(user_name, active_product.product_id)
        product_id = active_product.product_id
        cl.user_session.set("product_id", active_product.product_id)
        # Newly created product don't hav e product_name until the first spec is generated
        product_name = active_product.name
        if product_name:
            cl.user_session.set("product_name", product_name)

        if has_storage:
            await cl.Message(
                content=f"Welcome back, here is your last project: {product_name}.").send()
            await populate_from_cloud_storage(user_name, product_id)
            return
        else:
            # We are starting a new project
            await cl.Message(content="Let's build you new product. We can build it together one step at a time,"
                                     " or you can give me the full specification, and I will have it built.").send()
            return
    else:
        # When starting a new project for the first time, set the product_id to session_id
        cl.user_session.set("product_id", cl.user_session.get("id"))

    await cl.Message(
        content="Hello, I'm here to assist you with building your website. We can build it together one step at a time,"
                " or you can give me the full specification, and I will have it built.").send()


@cl.on_window_message
async def window_message(message: str | dict):
    method = "user_message"
    if isinstance(message, dict):
        method = message.get("method")

    product_id = cl.user_session.get("product_id")
    user_name = cl.user_session.get("user").identifier

    if method == "to_builder":
        await to_builder(user_name, product_id, message.get("body", "INVALID REQEUST, something went wrong"),
                         builder_completed, process_generator_message, ask_user)
    elif method == "to_generator":
        await to_generator(user_name, product_id, message.get("body", "INVALID REQEUST, something went wrong"),
                           generator_completed, process_generator_message, ask_user)
    elif method == "load_template":
        load_template(user_name, product_id, message.get("body"))
        await populate_from_cloud_storage(user_name, product_id)
    elif method == "deploy":
        site_name = message.get("body")
        # TODO: This needs to go away
        # TODO: optimize this. Product_id should come with the request from the forntend
        #  (in fact this is a bug that product is stored in session).
        product = await Product.find_one(Product.product_id == product_id)
        message_text = await run_deployment(user_name, product, site_name)

        await asyncio.gather(cl.Message(content=message_text).send(),
                             cl.send_window_message({"method": "deploy_status", "body": message_text}),
                             update_deployments_list(product.id))
    elif method == "create_new_product":
        await create_blank_product_for(user_name)
        await cl.send_window_message({"method": "reload_product"})
    elif method == "product_selected":
        await set_product_active(user_name, message.get("body"))
        await cl.send_window_message({"method": "reload_product"})
    else:
        # TODO: remove this, it is replaced by the "ask_user" function callback
        await cl.Message(content=message).send()


@cl.on_message
async def respond(message: Message):
    product_id = cl.user_session.get("product_id")
    user_name = cl.user_session.get("user").identifier

    if len(message.elements) > 0:
        # This happens when we are uploading a file from the chat window
        blob_image_path = save_image_file_to_private(user_name, product_id, message.elements[0].name,
                                                     message.elements[0].path,
                                                     message.content)
        message.content = f"Given: {blob_image_path} \n {message.content}"
    await to_builder(user_name, product_id, message.content, builder_completed, process_generator_message, ask_user)


@cl.password_auth_callback
async def auth_callback(username: str, password: str):
    user = await User.find_one(User.username == username)

    if verify_password(password, user.password_hash):
        return cl.User(
            identifier=username, metadata={"role": "user", "provider": "credentials"}
        )
    else:
        return None
