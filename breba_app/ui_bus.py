import asyncio

import chainlit as cl

from breba_app.models.product import Product


async def send_specification_to_ui(specification: str):
    await cl.send_window_message({"method": "to_builder", "body": specification})


async def send_index_html_to_ui(html: str):
    await cl.send_window_message({"method": "to_generator", "body": html})
    await cl.send_window_message({"method": "to_generator", "body": "__completed__"})


async def init_product_preview(url: str):
    await cl.send_window_message(
        {"method": "load_preview", "url": url})


async def reload_product_preview():
    await cl.send_window_message(
        {"method": "refresh_preview"})


async def send_index_html_chunk_to_ui(html: str):
    await cl.send_window_message({"method": "to_generator", "body": html})


async def update_product_name(product_id: str, new_name: str):
    await cl.send_window_message(
        {"method": "update_product_name", "body": {"product_id": product_id, "name": new_name}})


async def update_products_list(products: list[Product]):
    products_list = [{"product_id": product.product_id, "name": product.name, "active": product.active} for product in
                     products]
    await cl.send_window_message({"method": "update_products_list", "body": products_list})


async def update_versions_list(versions: list[int], active: int):
    await cl.send_window_message({"method": "update_versions_list", "body": {"versions": versions, "active": active}})


async def set_active_product(product_id: str):
    await cl.send_window_message({"method": "set_active_product", "body": product_id})


async def update_follow_up_questions_list(questions: list[str]):
    await cl.send_window_message({"method": "update_follow_up_questions_list", "body": questions})


async def signal_task_started():
    await cl.context.emitter.task_start()
    await asyncio.sleep(0.01)
    await cl.send_window_message({"method": "task_started"})


async def signal_task_completed():
    await cl.context.emitter.task_end()
    await asyncio.sleep(0.01)
    await cl.send_window_message({"method": "task_completed"})
