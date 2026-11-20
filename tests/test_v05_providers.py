import asyncio
import json

import httpx

from backend.core.config import resolve_model_route
from backend.providers.openai_compat import OpenAICompatibleProvider
from backend.providers.schemas import Message, ToolDefinition
from uuid import uuid4


def test_route_parser_supports_provider_prefix(monkeypatch) -> None:
    monkeypatch.setenv("DEFAULT_PROVIDER", "google")
    monkeypatch.setenv("MODEL_TIER_FAST", "groq:llama-3.3-70b-versatile")
    monkeypatch.setenv("MODEL_TIER_REASONING", "openrouter:deepseek/deepseek-r1:free")

    r_fast = resolve_model_route("fast")
    r_reason = resolve_model_route("reasoning")

    assert r_fast.provider == "groq"
    assert r_fast.model == "llama-3.3-70b-versatile"
    assert r_reason.provider == "openrouter"
    assert r_reason.model == "deepseek/deepseek-r1:free"


def test_openai_compatible_provider_parses_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "deepseek-chat"
        assert len(payload["tools"]) == 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_abc123",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path": "main.py"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 42,
                    "completion_tokens": 18,
                    "total_tokens": 60,
                },
            },
        )

    provider = OpenAICompatibleProvider(
        provider_id="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key="test-key",
    )
    provider._client = httpx.AsyncClient(
        base_url="https://api.deepseek.com/v1",
        transport=httpx.MockTransport(handler),
    )

    msg = Message(run_id=uuid4(), session_id=uuid4(), sequence=0, role="user", content="Lee main.py")
    tool = ToolDefinition(
        name="read_file",
        description="Lee un archivo",
        json_schema={"type": "object", "properties": {"path": {"type": "string"}}},
    )

    res = asyncio.run(provider.generate([msg], tools=[tool]))
    asyncio.run(provider.close())

    assert res.provider == "deepseek"
    assert res.finish_reason == "tool_calls"
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].tool_name == "read_file"
    assert res.tool_calls[0].arguments == {"path": "main.py"}
    assert res.usage.total_tokens == 60
