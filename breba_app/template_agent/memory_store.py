from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple

from breba_app.llm_utils import BrebaMessage
from breba_app.template_agent.baml_client.stream_types import LLMMessage


@dataclass
class TemplateAgentState:
    messages: List[BrebaMessage]


# Keyed by (user_id, product_id)
_state_store: Dict[Tuple[str, str], TemplateAgentState] = defaultdict(lambda: TemplateAgentState(messages=[]))


def load_state(user_id: str, product_id: str) -> TemplateAgentState:
    """Retrieve the current state for a given user/product pair."""
    return _state_store[(user_id, product_id)]


def save_state(user_id: str, product_id: str, state: TemplateAgentState) -> None:
    """Persist the given state for a user/product pair."""
    _state_store[(user_id, product_id)] = state
