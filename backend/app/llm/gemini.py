"""Gemini adapter: the only file that knows about the Google GenAI SDK.

Purpose: implement LlmClient on top of the Gemini Interactions API.
Input: system text, user text and a JSON Schema.
Output: the model's JSON text. Every provider failure is raised as LlmError.
Dependencies: google-genai.

Privacy: store=False asks Google not to keep the request for later retrieval. On the free
tier, Google may still use prompts to improve its products, so use only made-up data until
the project is on a paid tier with proper data terms.
"""

import logging
from typing import Any

from google import genai

from app.llm.base import LlmError

logger = logging.getLogger(__name__)


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 20.0,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._timeout = timeout_seconds
        # `client` can be injected so tests never touch the network.
        self._client = client or genai.Client(api_key=api_key)

    async def generate_json(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        try:
            interaction = await self._client.aio.interactions.create(
                model=self._model,
                input=user,
                system_instruction=system,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": schema,
                },
                store=False,
                timeout=self._timeout,
            )
        except Exception as exc:  # the SDK raises several error types; callers need just one
            logger.warning("gemini_call_failed", extra={"error_type": type(exc).__name__})
            raise LlmError(type(exc).__name__) from exc

        text = getattr(interaction, "output_text", None)
        if not text:
            raise LlmError("empty_response")
        return text
