"""A scripted stand-in for a language model, for tests and offline demos."""

from typing import Any

from app.llm.base import LlmError


class ScriptedLlmClient:
    """Returns queued responses in order. A queued Exception is raised instead of returned."""

    def __init__(self, *responses: str | Exception) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def generate_json(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        self.calls.append({"system": system, "user": user, "schema": schema})
        if not self._responses:
            raise LlmError("ScriptedLlmClient has no more responses")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
