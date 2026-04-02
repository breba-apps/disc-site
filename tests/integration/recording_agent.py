import json
import re
from pathlib import Path

from langchain_core.messages import BaseMessage, message_to_dict
from langchain_openai import ChatOpenAI

from breba_app.config import load_env

load_env()


def normalize_kwargs(args):
    str_args = json.dumps(args, default=str)
    args_without_id = re.sub(r"\s*id='[^']*'", '', str_args)
    return args_without_id


def normalize_args(args):
    str_args = json.dumps(args[0], default=str)
    args_without_id = re.sub(r"\s*id='[^']*'", '', str_args)
    return args_without_id


class RecordingChatOpenAI(ChatOpenAI):
    def __init__(self, test_name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._path = Path(f"./tests/integration/fixtures/{test_name}.json")

        recordings = []
        if self._path.exists():
            recordings = json.loads(self._path.read_text())
        else:
            self._path.parent.mkdir(parents=True, exist_ok=True)

        self._recordings = recordings or []
        self._index = 0

    def _record_call(self, method_name, result: BaseMessage, *args, **kwargs):
        self._recordings.append({
            "method": method_name,
            "args": normalize_args(args),
            "kwargs": normalize_kwargs(kwargs) if kwargs else kwargs,
            "result": message_to_dict(result)
        })
        # Rewrite the whole file
        with open(self._path, "w") as f:
            json.dump(self._recordings, f, indent=2, default=str)

    async def ainvoke(self, *args, **kwargs):
        if self._index < len(self._recordings):
            if (self._recordings[self._index]["method"] == "ainvoke" and
                    self._recordings[self._index]["args"] == normalize_args(args) and
                    self._recordings[self._index]["kwargs"] == normalize_kwargs(kwargs)):
                return_val = self._recordings[self._index]["result"]
                return_val = messages_from_dict([return_val])[0]  # This is just on AIMessage really
                self._index += 1
            else:
                raise Exception(
                    f"Unexpected call to ainvoke: {self._recordings[self._index]}, consider updating snapshot")
        else:
            return_val = await super().ainvoke(*args, **kwargs)
            self._record_call("ainvoke", return_val, *args, **kwargs)
        return return_val

# @pytest.mark.asyncio
# async def test_stream_has_current_date(tmp_path):
#     query = "Create a simple Hello World site"
#     session_id = "test-session"
#     user_name = "test-user"
#     fixed_dt = datetime.datetime(2023, 1, 1, 15, 30, 0)
#
#     agent = HTMLAgent()
#
#     try:
#         with patch("breba_app.generator_agent.agent.ChatOpenAI",
#                    lambda *args, **kwargs: RecordingChatOpenAI("test_stream_has_current_date", *args, **kwargs)), \
#                 patch("breba_app.generator_agent.agent.datetime") as mock_datetime:
#             # TODO: datetime should come form some sort of context getter, and we would mock the getter
#             # We want to make sure the timestamp is the same across all calls.
#             mock_datetime.datetime.now.return_value = fixed_dt
#             mock_datetime.datetime.strftime = datetime.datetime.strftime
#
#             await agent.ensure_initialized(os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN"))
#
#             # Run the agent's stream method
#             async for _ in agent.stream(query=query, user_name=user_name, session_id=session_id):
#                 pass
#
#             model_calls = agent.model._recordings
#             assert "Current time is: 2023-01-01 15:30:00" in model_calls[0]["args"]
#
#     finally:
#         if agent._initialized:
#             await agent.close()
