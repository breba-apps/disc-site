import logging
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader
from openai import AsyncOpenAI


@dataclass
class BrebaElement:
    path: str
    name: str


@dataclass
class BrebaMessage:
    role: Literal["user", "assistant"]
    content: str
    elements: list[BrebaElement] = field(default_factory=list)

_client: AsyncOpenAI | None = None

logger = logging.getLogger(__name__)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()
    return _client

USER_ROLE = "user"
MAX_MESSAGES = 100
MAX_WORDS = 20_000
MAX_IMAGES = 30

_LLM_SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def is_llm_supported_image(content_type: str | None) -> bool:
    """Return True if the MIME type is accepted as inline image input by the LLM API."""
    return content_type in _LLM_SUPPORTED_IMAGE_TYPES


def trim(messages: list[BrebaMessage]) -> list[BrebaMessage]:
    result = []
    total_words = 0
    total_images = 0

    for message in reversed(messages):
        words = len(message.content.split())
        images = len(message.elements)

        if total_words + words > MAX_WORDS or total_images + images > MAX_IMAGES or len(result) >= MAX_MESSAGES:
            break

        result.insert(0, message)
        total_words += words
        total_images += images

    # Ensure the conversation starts with a user message
    while result and result[0].role != USER_ROLE:
        result.pop(0)

    return result

async def get_product_name(description: str) -> str:
    if not description:
        raise ValueError("description cannot be empty")

    prompt = (
        f"Create a product name given the description. *Important:* your response must be one to three words long."
        f" <BEGIN DESCRIPTION>\n{description}\n<END DESCRIPTION>\n\n"
        f"**Your response must be a one to three words long description of the product above.**")

    try:
        response = await _get_client().responses.create(model="gpt-5-nano", input=prompt,
                                                 reasoning={"effort": "minimal"},
                                                 text={"verbosity": "low"})
        return response.output_text
    except Exception as e:
        logger.error(f"Product name generation failed: {e}")
        # This is not a critical function. Just return the first word of the description
        return description.split()[0]


def get_instructions(agent_dir: Path, name, **kwargs):
    env = Environment(loader=FileSystemLoader(agent_dir / "instructions"))
    template = env.get_template(f"{name}.jinja2")
    return template.render(**kwargs)
