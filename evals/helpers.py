from __future__ import annotations

from pathlib import Path

from openai import Client

from breba_app.coder_agent.agent import FileStore
from breba_app.coder_agent.baml_client.types import LLMMessage
from evals.loader import load_evals

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client()
    return _client


EVALUATION_PROMPT = "You are evaluating correctness. Just answer the question. No comments or explanations. Just the answer."
EVALUATION_MODEL = "gpt-4.1-mini"


def _render_file(file_name: str, file_content: str) -> str:
    return f"""{file_name}
```
{file_content}
```
"""


def combine_agent_response_with_files(agent_response: LLMMessage, store: FileStore) -> str:
    files_content = ""
    for file_name in store.list_files():
        file_content = store.read_text(file_name)
        files_content += _render_file(file_name, file_content)
    return (
        f"<project_files>"
        f"<description>\nThe following files exist in the project. Use these files to evaluate content. We don't know if the files were modified\n</description>"
        f"\n{files_content}\n</project_files>\n\n"
        f"<agent_response>\n{agent_response.content}\n</agent_response>")


async def run_evals(case_dir: Path, text: str):
    evals = load_evals(case_dir)
    for evaluation in evals:
        eval_message_content = (f"Given the following text:\n{text}\n\n"
                                f"{evaluation['question']}\n"
                                f"Your allowed answer options: {evaluation.get('answer_options', 'answer options are not restricted')}\n")
        result = _get_client().responses.create(
            model=EVALUATION_MODEL,
            temperature=0,
            top_p=1,
            input=[
                {"role": "system", "content": EVALUATION_PROMPT},
                {"role": "user", "content": eval_message_content}
            ])
        print(eval_message_content)
        assert result.output_text.lower().strip() == evaluation["expected_answer"]


class StreamUserCallback:
    def __init__(self):
        self.sideeffect = ""

    async def __call__(self, stream_or_text):
        if hasattr(stream_or_text, "__aiter__"):
            async for token_sequence in stream_or_text:
                self.sideeffect = token_sequence
