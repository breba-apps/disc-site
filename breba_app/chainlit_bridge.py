import base64
import mimetypes
from pathlib import Path

import chainlit as cl
from baml_py import Image

from breba_app.coder_agent.baml_client.types import LLMMessage


def to_llm_message(message: cl.Message) -> LLMMessage:
    images = []
    for el in (message.elements or []):
        content_type, _ = mimetypes.guess_type(el.name)
        if content_type and content_type.startswith("image/"):
            media_type = content_type or "image/jpeg"
            images.append(Image.from_base64(media_type, base64.b64encode(Path(el.path).read_bytes()).decode()))
    return LLMMessage(role="user", content=message.content, images=images if images else None)
