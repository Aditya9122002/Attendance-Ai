import pytest

from app.llm.base import LlmError
from app.llm.gemini import GeminiClient

SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}}


class FakeInteraction:
    def __init__(self, output_text):
        self.output_text = output_text


class FakeInteractions:
    def __init__(self, result):
        self.result = result
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeAio:
    def __init__(self, interactions):
        self.interactions = interactions


class FakeSdkClient:
    def __init__(self, result):
        self.interactions = FakeInteractions(result)
        self.aio = FakeAio(self.interactions)


async def test_sends_schema_system_prompt_and_disables_storage():
    sdk = FakeSdkClient(FakeInteraction('{"x": "y"}'))
    client = GeminiClient("key", "gemini-test", client=sdk)
    text = await client.generate_json(system="sys", user="hello", schema=SCHEMA)
    sent = sdk.interactions.kwargs
    assert text == '{"x": "y"}'
    assert sent["model"] == "gemini-test"
    assert sent["input"] == "hello"
    assert sent["system_instruction"] == "sys"
    assert sent["store"] is False
    assert sent["response_format"]["mime_type"] == "application/json"
    assert sent["response_format"]["schema"] == SCHEMA


async def test_sdk_error_becomes_llm_error():
    sdk = FakeSdkClient(RuntimeError("429 quota"))
    client = GeminiClient("key", "gemini-test", client=sdk)
    with pytest.raises(LlmError):
        await client.generate_json(system="s", user="u", schema=SCHEMA)


async def test_empty_response_becomes_llm_error():
    sdk = FakeSdkClient(FakeInteraction(""))
    client = GeminiClient("key", "gemini-test", client=sdk)
    with pytest.raises(LlmError):
        await client.generate_json(system="s", user="u", schema=SCHEMA)
