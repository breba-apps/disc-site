from typing import AsyncIterable

from breba_app.chainlit_bridge import to_baml_message
from breba_app.llm_utils import BrebaMessage, trim
from breba_app.status_service import update_status
from breba_app.template_agent.baml_client.async_client import b
from breba_app.template_agent.baml_client.stream_types import Question as StreamQuestion, \
    WebsiteSpecification as StreamWebSpecification
from breba_app.template_agent.baml_client.types import WebsiteSpecification, Question
from breba_app.template_agent.memory_store import load_state, save_state


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
    def __init__(self, user_id: str, product_id: str):
        self.user_id = user_id
        self.product_id = product_id
        self.state = load_state(user_id, product_id)

    async def build_specification(self, message: BrebaMessage,
                                  ask_user_streaming_callback) -> WebsiteSpecification | Question:
        self.state.messages.append(message)
        trimmed = trim(self.state.messages)
        baml_messages = [to_baml_message(m) for m in trimmed]

        if baml_messages:
            stream = b.stream.GenerateSpecificationFromTemplate(baml_messages)
            await ask_user_streaming_callback(to_user_stream(stream))
            agent_response = await stream.get_final_response()
            if isinstance(agent_response, Question):
                self.state.messages.append(BrebaMessage(role="assistant", content=agent_response.question))
            elif isinstance(agent_response, WebsiteSpecification):
                self.state.messages.append(BrebaMessage(role="assistant", content=agent_response.spec))
            save_state(self.user_id, self.product_id, self.state)
        else:
            self.state.messages.pop()
            error_message = "Your message exceeds the context limit. Please provide a shorter description."
            update_status(error_message)
            agent_response = Question(question=error_message)

        return agent_response
