from typing import AsyncIterable

from langchain_core.messages import trim_messages
from langchain_core.messages.utils import count_tokens_approximately, convert_to_openai_messages

from breba_app.chainlit_bridge import BrebaMessage
from breba_app.status_service import update_status
from breba_app.template_agent.baml_client.async_client import b
from breba_app.template_agent.baml_client.stream_types import Question as StreamQuestion, LLMMessage, \
    WebsiteSpecification as StreamWebSpecification
from breba_app.template_agent.baml_client.types import WebsiteSpecification, Question
from breba_app.template_agent.memory_store import load_state, save_state

TOKEN_LIMIT = 100_000


async def to_user_stream(streamer: AsyncIterable[StreamQuestion | StreamWebSpecification]):
    async for msg in streamer:
        if type(msg) is StreamQuestion:
            # For some reason when streaming WebSpecification, the first message is empty question.
            if not msg.question:
                continue
            yield msg.question
        if type(msg) is StreamWebSpecification:
            update_status("Builder is working on the specification...")
            break


class TemplateAgent:
    def __init__(self, user_name: str, product_id: str, messages: list[LLMMessage] | None = None):
        self.user_name = user_name
        self.product_id = product_id
        self.state = load_state(user_name, product_id)
        if messages:
            self.state.messages = messages

    async def build_specification(self, message: BrebaMessage, ask_user_streaming_callback) -> WebsiteSpecification | Question:
        baml_msg = message.to_baml_message()
        self.state.messages.append(LLMMessage(role="user", content=baml_msg.content, images=baml_msg.images))
        dict_messages = [message.model_dump() for message in self.state.messages]
        # "human" is the langchain type for "user" role messages
        trimmed_messages_lc = trim_messages(dict_messages, strategy="last",
                                            token_counter=count_tokens_approximately, max_tokens=TOKEN_LIMIT,
                                            start_on=["human"], include_system=True)

        trimmed_messages = convert_to_openai_messages(trimmed_messages_lc)

        if trimmed_messages:
            # We are just going to pass a dict that has proper duck type
            stream = b.stream.GenerateSpecificationFromTemplate(trimmed_messages)
            await ask_user_streaming_callback(to_user_stream(stream))
            agent_response = await stream.get_final_response()
            if isinstance(agent_response, Question):
                self.state.messages.append(LLMMessage(role="assistant", content=agent_response.question))
            elif isinstance(agent_response, WebsiteSpecification):
                self.state.messages.append(LLMMessage(role="assistant", content=agent_response.spec))
            save_state(self.user_name, self.product_id, self.state)
        else:
            # This will only happen when the last user message is very long.
            # We do not want to add it to the state because it will hide all older messages. So we will not save state
            self.state.messages.pop()
            error_message = f"You have exceeded the token limit({TOKEN_LIMIT} tokens). Please provide a shorter description."
            update_status(error_message)
            agent_response = Question(question=error_message)

        return agent_response
