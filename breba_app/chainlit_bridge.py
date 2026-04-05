import base64
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import chainlit as cl
from baml_py import Image

from breba_app.coder_agent.baml_client.types import LLMMessage


@dataclass
class BrebaElement:
    path: str
    name: str


@dataclass
class BrebaMessage:
    role: Literal["user", "assistant"]
    content: str
    elements: list[BrebaElement] = field(default_factory=list)

    def to_baml_message(self) -> LLMMessage:
        images = []
        for el in self.elements:
            content_type, _ = mimetypes.guess_type(el.name)
            if content_type and content_type.startswith("image/"):
                images.append(Image.from_base64(content_type, base64.b64encode(Path(el.path).read_bytes()).decode()))
        return LLMMessage(role=self.role, content=self.content, images=images if images else None)


def from_cl_message(message: cl.Message) -> BrebaMessage:
    elements = [BrebaElement(path=el.path, name=el.name) for el in (message.elements or [])]
    return BrebaMessage(role="user", content=message.content, elements=elements)
