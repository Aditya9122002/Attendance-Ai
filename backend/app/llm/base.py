"""The small interface the rest of the app uses to talk to any language model.

Purpose: keep provider-specific code (Gemini, others later) in one adapter file.
Input: a system instruction, the user text, and a JSON Schema the answer must follow.
Output: the model's raw JSON text. The caller validates it.
Dependencies: none.
"""

from typing import Any, Protocol


class LlmError(Exception):
    """The provider failed: network error, rate limit, timeout, or a blocked response."""


class LlmClient(Protocol):
    async def generate_json(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        """Return JSON text that should follow `schema`. Raise LlmError on provider failure."""
        ...
