import asyncio
import json
import logging
from typing import AsyncIterator

import chainlit as cl
import httpx
from beanie import SortDirection
from bson import DBRef
from chainlit import Message

import breba_app.ui_bus as ui_bus
from auth import verify_password
from breba_app.builder import build
from breba_app.chainlit_bridge import from_cl_message
from breba_app.config import SPEC_FILE_NAME, INDEX_FILE_NAME
from breba_app.controllers.product_controller import delete_product, rename_product
from breba_app.events.bus import HandleContext, Consumer, event_bus
from breba_app.events.coder_completed import CoderCompleted
from breba_app.filesystem import InMemoryFileStore, FileWrite
from breba_app.github_controller import deploy_to_github
from breba_app.github_deploy import get_pages_url
from breba_app.llm_utils import BrebaMessage
from breba_app.context import init_context
from breba_app.models.deployment import Deployment
from breba_app.models.product import Product, create_or_update_product_for, create_blank_product_for, set_product_active
from breba_app.models.user import User
from breba_app.orchestrator import handle_user_message, start_product, \
    handle_file_upload, init_orchestrator
from breba_app.storage import has_cloud_storage, list_versions, get_active_version, set_version_active, \
    read_all_files_in_memory, save_files, get_index_html_path
from breba_app.template_agent.product_types.landing_page import landing_page_instructions, \
    landing_page_follow_up_questions
from breba_app.ui_bus import update_products_list, update_versions_list, update_follow_up_questions_list
from breba_app.website import build_preview
from controllers.deployment_controller import run_deployment
from llm_utils import get_product_name
from storage import get_public_url

logger = logging.getLogger(__name__)

PRODUCT_NAME_PLACEHOLDER = "Unnamed Product"


class ProductNameAssignmentConsumer(Consumer):
    def __init__(self, user_id: str, product_id: str):
        self.id = f"product_name_assignment_{user_id}_{product_id}"
        super().__init__()

    async def handle(self, ctx: HandleContext, event: CoderCompleted) -> None:
        product_name = await get_product_name(event.filestore.read_text(INDEX_FILE_NAME))
        product = await create_or_update_product_for(event.user_id, event.product_id, product_name)
        cl.user_session.set("product_name", product.name)
        await ui_bus.update_product_name(event.product_id, product.name)
        # The first time
        await ui_bus.init_product_preview(get_index_html_path(event.product_id))
        await ctx.unsubscribe_self()


async def ask_user_streaming(token_stream: AsyncIterator[str] | str):
    if isinstance(token_stream, str):
        msg = cl.Message(content=token_stream)
    else:
        msg = cl.Message(content="")

        # Stream each token into it as they arrive
        async for chunk in token_stream:
            if not chunk:
                continue
            await msg.stream_token(chunk, is_sequence=True)

    # Send the fully streamed message once complete
    if msg.content:
        await msg.send()


async def populate_from_cloud_storage(user_id: str, session_id: str):
    index_path = get_index_html_path(session_id)
    state, _ = await asyncio.gather(init_orchestrator(user_id, session_id),
                                    ui_bus.init_product_preview(index_path))
    await ui_bus.set_active_product(session_id)

    filestore = state.filestore

    spec = ""
    if filestore.file_exists(SPEC_FILE_NAME):
        spec = filestore.read_text(SPEC_FILE_NAME)

    await asyncio.gather(
        ui_bus.send_specification_to_ui(spec)
    )


async def coder_completed(user_id: str, product_id: str, file_store: InMemoryFileStore):
    """
    This is called when the coder agent is done.
    It will update the UI with the updated files
    It will also persist the files to the cloud storage

    :param user_id: mongo user id used for storage namespacing
    :param product_id: used to identify the session
    :param file_store the in memory file store provided by the coder agent
    """
    spec = ""
    if file_store.file_exists("spec.txt"):
        spec = file_store.read_text("spec.txt")

    # First we persist the files and preview
    files_to_save: list[FileWrite] = list(file_store.snapshot().values())
    new_version, _ = await asyncio.gather(save_files(user_id, product_id, files_to_save),
                                          build_preview(product_id, file_store))

    _, _, versions = await asyncio.gather(
        ui_bus.send_specification_to_ui(spec),
        ui_bus.reload_product_preview(),
        list_versions(user_id, product_id)
    )

    await update_versions_list(versions, new_version)
    # TODO: This is just the first step. This entire callback should go away once event bus is work. That is the purpose of the event bus.
    await event_bus.emit(CoderCompleted(user_id=user_id, product_id=product_id, filestore=file_store))


async def update_deployments_list(product: Product):
    deployments = await Deployment.find(Deployment.product == DBRef("products", product.id)).sort(
        [("deployed_at", SortDirection.DESCENDING)]).to_list()

    deployments_list = [{"id": str(deployment.id), "deployment_id": deployment.deployment_id,
                         "url": get_public_url(deployment.deployment_id), "type": "breba"} for deployment in
                        deployments]

    if product.github_repo:
        org, repo_name = product.github_repo.split("/", 1)
        pages_url = get_pages_url(org, repo_name)
        deployments_list.append({
            "id": "github",
            "url": pages_url,
            "repo_url": f"https://github.com/{product.github_repo}",
            "type": "github",
        })

    await cl.send_window_message({"method": "update_deployments_list", "body": deployments_list})
    await cl.send_window_message({"method": "github_product_status", "body": {
        "github_repo": product.github_repo,
        "custom_domain": product.custom_domain,
        "product_id": product.product_id,
    }})

async def _discover_user_and_product() -> tuple[User | None, Product | None]:
    user_name = cl.user_session.get("user").identifier
    user = await User.find_one(User.username == user_name, fetch_links=True)
    if not user:
        return None, None

    active_product = await Product.find_one(Product.user.id == user.id, Product.active == True)
    if not active_product:
        active_product = await Product.find(
            Product.user.id == user.id
        ).sort([("_id", SortDirection.DESCENDING)]).first_or_none()

    return user, active_product


async def restore_product(user_id: str, active_product: Product) -> None:
    product_id = active_product.product_id

    versions = await list_versions(user_id, product_id)
    active_version = await get_active_version(user_id, product_id)
    asyncio.create_task(update_versions_list(versions, active_version))
    asyncio.create_task(update_deployments_list(active_product))

    has_storage = await has_cloud_storage(user_id, product_id)
    product_name = active_product.name

    if not product_name or product_name == PRODUCT_NAME_PLACEHOLDER:
        await event_bus.subscribe(CoderCompleted, ProductNameAssignmentConsumer(user_id, product_id))
    elif product_name:
        cl.user_session.set("product_name", product_name)

    if has_storage:
        await cl.Message(content=f"Welcome back, here is your last project: {product_name}.").send()
        await populate_from_cloud_storage(user_id, product_id)
        await update_follow_up_questions_list(landing_page_follow_up_questions)
    else:
        await cl.Message(
            content="Let's build you new product. We can build it together one step at a time,"
                    " or you can give me the full specification, and I will have it built."
        ).send()


async def load_new_product(user_id: str | None, product_id: str) -> None:
    if user_id:
        await asyncio.gather(
            create_blank_product_for(user_id, PRODUCT_NAME_PLACEHOLDER, True),
            event_bus.subscribe(CoderCompleted, ProductNameAssignmentConsumer(user_id, product_id)),
            ui_bus.set_active_product(product_id),
        )
    await cl.Message(
        content="Hello, I'm here to assist you with building your website. We can build it together one step at a time,"
                " or you can give me the full specification, and I will have it built."
    ).send()


@cl.on_chat_start
async def main():
    # Phase 1: discover
    user, active_product = await _discover_user_and_product()

    # Phase 2: initialize context (one-shot, no merging)
    user_id = str(user.id) if user else None
    product_id = active_product.product_id if active_product else cl.user_session.get("id")
    init_context(user_id=user_id, product_id=product_id)
    if user_id:
        cl.user_session.set("user_id", user_id)
    cl.user_session.set("product_id", product_id)

    # Phase 3: dispatch
    if user:
        await cl.send_window_message({"method": "logged_in"})
        asyncio.create_task(update_products_list(user.products))

    if active_product:
        await restore_product(user_id, active_product)
    else:
        await load_new_product(user_id, product_id)


@cl.on_window_message
async def window_message(message: str | dict):
    method = "user_message"
    if isinstance(message, dict):
        method = message.get("method")

    # TODO: This needs to go away
    # TODO: optimize this. Product_id should come with the request from the forntend
    #  (in fact this is a bug that product is stored in session).
    product_id = cl.user_session.get("product_id")
    user_id = cl.user_session.get("user_id")
    init_context(user_id=user_id, product_id=product_id)

    await _window_message_dispatch(method, message, user_id, product_id)


async def _window_message_dispatch(method, message, user_id, product_id):
    if method == "set_active_page":
        cl.user_session.set("current_page", message.get("body"))
    elif method == "to_builder":
        current_page = cl.user_session.get("current_page")
        await handle_user_message(user_id, product_id,
                                  BrebaMessage(role="user",
                                               content=message.get("body", "INVALID REQEUST, something went wrong")),
                                  coder_completed_callback=coder_completed,
                                  stream_to_user_callback=ask_user_streaming,
                                  current_page=current_page)
    elif method == "to_generator":
        current_page = cl.user_session.get("current_page")
        await handle_user_message(user_id, product_id,
                                  BrebaMessage(role="user",
                                               content=message.get("body", "INVALID REQEUST, something went wrong")),
                                  coder_completed_callback=coder_completed,
                                  stream_to_user_callback=ask_user_streaming,
                                  current_page=current_page)
    elif method == "load_template":
        await start_product(
            user_id, product_id,
            BrebaMessage(role="user", content=landing_page_instructions),
            coder_completed,
            ask_user_streaming
        )
        await update_follow_up_questions_list(landing_page_follow_up_questions)
    elif method == "deploy":
        site_name = message.get("body")
        product = await Product.find_one(Product.product_id == product_id)
        message_text = await run_deployment(user_id, product, site_name)

        await asyncio.gather(cl.Message(content=message_text).send(),
                             cl.send_window_message({"method": "deploy_status", "body": message_text}),
                             update_deployments_list(product))
    elif method == "deploy_github":
        org = message.get("body", {}).get("org")
        source = await read_all_files_in_memory(user_id, product_id)
        built = build(source)
        result = await deploy_to_github(user_id, product_id, built, org=org)
        await cl.send_window_message({"method": "github_deploy_status", "body": {
            "success": result.success,
            "pages_url": result.pages_url,
            "repo_url": result.repo_url,
            "error": result.error,
        }})
        if result.success:
            product = await Product.find_one(Product.product_id == product_id)
            await asyncio.gather(
                cl.Message(
                    content=f"Deployed to GitHub Pages: {result.pages_url}\n\nNote: GitHub Pages can take 1–2 minutes to publish."
                ).send(),
                update_deployments_list(product),
            )
        else:
            await cl.Message(content=f"GitHub deploy failed: {result.error}").send()
    elif method == "create_new_product":
        await create_blank_product_for(user_id, PRODUCT_NAME_PLACEHOLDER, True)
        await cl.send_window_message({"method": "reload_product"})
    elif method == "product_selected":
        await set_product_active(user_id, message.get("body"))
        await cl.send_window_message({"method": "reload_product"})
    elif method == "delete_product":
        await delete_product(user_id, message.get("body"))
        await cl.send_window_message({"method": "reload_product"})
    elif method == "rename_product":
        body = message.get("body", {})
        product_id_to_rename = body.get("productId")
        new_name = body.get("newName")
        await rename_product(user_id, product_id_to_rename, new_name)
        if product_id == product_id_to_rename:
            cl.user_session.set("product_name", new_name)
    elif method == "select_version":
        version = int(message.get("body"))
        await set_version_active(user_id, product_id, version)
        # After setting version, we need to rebuild preview
        filestore = await read_all_files_in_memory(user_id, product_id, version)
        await build_preview(product_id, filestore)
        # To avoid race condition, we want to wait for the preview to build, before reloading product
        await cl.send_window_message({"method": "reload_product"})
    else:
        # TODO: remove this, it is replaced by the "ask_user" function callback
        await cl.Message(content=message).send()


@cl.on_message
async def respond(message: Message):
    product_id = cl.user_session.get("product_id")
    user_id = cl.user_session.get("user_id")
    init_context(user_id=user_id, product_id=product_id)

    breba_message = from_cl_message(message)

    if len(message.elements) > 0:
        await handle_file_upload(user_id, product_id, breba_message, coder_completed, ask_user_streaming)
    else:
        # TODO: need some error handling here similar to the above or better
        current_page = cl.user_session.get("current_page")
        await handle_user_message(user_id, product_id, breba_message, coder_completed_callback=coder_completed,
                                  stream_to_user_callback=ask_user_streaming, current_page=current_page)


@cl.password_auth_callback
async def auth_callback(username: str, password: str):
    user = await User.find_one(User.username == username)

    if verify_password(password, user.password_hash):
        return cl.User(
            identifier=username, metadata={"role": "user", "provider": "credentials"}
        )
    else:
        return None


async def add_to_waitlist(email: str, comments: str):
    url = (
        "https://script.google.com/macros/s/"
        "AKfycbwCbKjWjO4ZkDWzFCeh7zo7e1rnHu6OP-ydwlJVJRyp-AjGav1gaG_5N1yEzOArvklW/exec"
    )

    payload = {"email": email,
               "comments": comments}

    try:
        http_client = httpx.AsyncClient(follow_redirects=True, timeout=8.0)
        resp = await http_client.post(
            url,
            content=json.dumps(payload),  # body: JSON string
            headers={
                "Content-Type": "text/plain;charset=utf-8",
            },
        )
        resp.raise_for_status()
    except Exception:
        logger.exception("Failed to send request to Apps Script")


@cl.oauth_callback
async def oauth_callback(
        provider_id: str,
        token: str,
        raw_user_data: dict[str, str],
        default_user: cl.User,
) -> cl.User | None:
    asyncio.create_task(
        add_to_waitlist(
            default_user.identifier,
            f"Name: {raw_user_data.get("name")}, Given Name: {raw_user_data.get("given_name")}"
        )
    )
    return default_user
