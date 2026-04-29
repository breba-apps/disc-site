from pydantic import BaseModel, ConfigDict

from breba_app.coder_agent.baml_client.types import LLMMessage
from breba_app.filesystem import InMemoryFileStore


class BeforeHandoffToCoder(BaseModel):
    """
    Event payload for "BeforeHandoffToCoder".
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    product_id: str
    messages: list[LLMMessage]
    filestore: InMemoryFileStore
