import base64
import mimetypes
from pathlib import Path

import chainlit as cl
from baml_py import Image

from breba_app.coder_agent.baml_client.types import LLMMessage
from breba_app.llm_utils import BrebaElement, BrebaMessage, is_llm_supported_image


def to_baml_message(message: BrebaMessage) -> LLMMessage:
    images = []
    for el in message.elements:
        content_type, _ = mimetypes.guess_type(el.name)
        if is_llm_supported_image(content_type):
            images.append(Image.from_base64(content_type, base64.b64encode(Path(el.path).read_bytes()).decode()))
    return LLMMessage(role=message.role, content=message.content, images=images if images else None)


def from_cl_message(message: cl.Message) -> BrebaMessage:
    elements = [BrebaElement(path=el.path, name=el.name) for el in (message.elements or [])]
    return BrebaMessage(role="user", content=message.content, elements=elements)
