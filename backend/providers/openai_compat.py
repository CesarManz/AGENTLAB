import re
import asyncio
import json
import os
import time
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import httpx

from backend.providers.base import BaseProvider
from backend.providers.schemas import (
    LLMResponse,
    Message,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class OpenAICompatibleProvider(BaseProvider):
    """
    Adaptador universal para cualquier API compatible con OpenAI Chat Completions:
    - Groq (https://api.groq.com/openai/v1)
    - OpenRouter (https://openrouter.ai/api/v1)
    - DeepSeek (https://api.deepseek.com/v1)
    - Ollama local (http://localhost:11434/v1)
    """

    def __init__(
        self,
        *,
        provider_id: str,
        model: str,
        base_url: str,
        api_key: str | None = None,
        max_retries: int = 4,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._provider_id = provider_id
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or "local-no-key"
        self.max_retries = max_retries

        headers: dict[str, str] = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter.ai" in self.base_url:
            headers["HTTP-Referer"] = "http://localhost:5173"
            headers["X-Title"] = "AGENT LAB Local Studio"

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout_seconds,
        )

    @property
    def provider_name(self) -> str:
        return self._provider_id

    def _to_openai_messages(
        self,
        messages: Sequence[Message],
        system_instruction: str | None,
    ) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        if system_instruction:
            payload.append({"role": "system", "content": system_instruction})

        for msg in messages:
            if msg.role == "user":
                payload.append({"role": "user", "content": msg.content or ""})
            elif msg.role == "assistant":
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content,
                }
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.tool_name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                payload.append(entry)
            elif msg.role == "tool":
                payload.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id or "",
                        "content": msg.content or "",
                    }
                )
        return payload

    def _to_openai_tools(
        self, tools: Sequence[ToolDefinition] | None
    ) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.json_schema,
                },
            }
            for t in tools
        ]

    @staticmethod
    def _extract_retry_delay(resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("retry-after")
        if retry_after:
            try:
                return min(65.0, max(1.0, float(retry_after) + 0.5))
            except ValueError:
                pass
        match = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", resp.text, re.IGNORECASE)
        if match:
            return min(65.0, max(1.5, float(match.group(1)) + 0.75))
        return min(30.0, float(2 ** (attempt + 1)))

    def _map_finish_reason(self, raw_reason: str | None, has_tool_calls: bool) -> str:
        if has_tool_calls:
            return "tool_calls"
        reason = (raw_reason or "").lower()
        if reason == "length":
            return "max_tokens"
        if reason == "content_filter":
            return "safety"
        return "stop"

    async def generate(
        self,
        messages: Sequence[Message],
        *,
        system_instruction: str | None = None,
        tools: Sequence[ToolDefinition] | None = None,
        temperature: float = 0.2,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        start = time.perf_counter()

        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_openai_messages(messages, system_instruction),
            "temperature": temperature,
        }
        openai_tools = self._to_openai_tools(tools)
        if openai_tools:
            body["tools"] = openai_tools
            body["tool_choice"] = "auto"

        if response_schema:
            body["response_format"] = {"type": "json_object"}

        last_error: str | None = None
        data: dict[str, Any] | None = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._client.post("/chat/completions", json=body)
                if resp.status_code in TRANSIENT_STATUS_CODES and attempt < self.max_retries:
                    last_error = f"HTTP {resp.status_code} ({self._provider_id}): {resp.text[:300]}"
                    await asyncio.sleep(self._extract_retry_delay(resp, attempt))
                    continue
                if resp.status_code >= 400:
                    last_error = f"HTTP {resp.status_code} ({self._provider_id}): {resp.text[:400]}"
                    break
                data = resp.json()
                last_error = None
                break
            except Exception as exc:
                last_error = f"Error de red ({self._provider_id}): {exc}"
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                break

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        if last_error is not None or data is None:
            return LLMResponse(
                content=last_error or "Error desconocido en proveedor OpenAI-compatible.",
                provider=self.provider_name,
                model_name=self.model,
                finish_reason="error",
                latency_ms=elapsed_ms,
            )

        choices = data.get("choices") or []
        first_choice = choices[0] if choices else {}
        message_obj = first_choice.get("message") or {}

        text_content: str | None = message_obj.get("content")
        raw_tool_calls = message_obj.get("tool_calls") or []
        extracted_calls: list[ToolCall] = []

        for tc in raw_tool_calls:
            fn = tc.get("function") or {}
            fn_name = fn.get("name")
            if not fn_name:
                continue
            raw_args = fn.get("arguments") or "{}"
            try:
                parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                parsed_args = {"_raw": str(raw_args)}

            extracted_calls.append(
                ToolCall(
                    id=tc.get("id") or f"call_{uuid4().hex[:12]}",
                    tool_name=fn_name,
                    arguments=parsed_args,
                )
            )

        parsed_output: dict[str, Any] | None = None
        if response_schema and text_content:
            try:
                loaded = json.loads(text_content)
                if isinstance(loaded, dict):
                    parsed_output = loaded
            except json.JSONDecodeError:
                parsed_output = None

        usage_obj = data.get("usage") or {}
        usage = TokenUsage(
            input_tokens=usage_obj.get("prompt_tokens"),
            output_tokens=usage_obj.get("completion_tokens"),
            total_tokens=usage_obj.get("total_tokens"),
        )

        finish_reason = self._map_finish_reason(
            first_choice.get("finish_reason"),
            has_tool_calls=len(extracted_calls) > 0,
        )

        return LLMResponse(
            content=text_content,
            parsed_output=parsed_output,
            tool_calls=tuple(extracted_calls),
            usage=usage,
            provider=self.provider_name,
            model_name=self.model,
            finish_reason=finish_reason,  # type: ignore[arg-type]
            latency_ms=elapsed_ms,
        )

    async def close(self) -> None:
        await self._client.aclose()


def build_openai_compatible_provider(provider_id: str, model: str) -> OpenAICompatibleProvider:
    """
    Fábrica preconfigurada para proveedores gratuitos y locales estándar.
    """
    pid = provider_id.lower().strip()
    if pid == "groq":
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise ValueError("Falta GROQ_API_KEY en el archivo .env")
        return OpenAICompatibleProvider(
            provider_id="groq",
            model=model,
            base_url="https://api.groq.com/openai/v1",
            api_key=key,
        )
    if pid == "openrouter":
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise ValueError("Falta OPENROUTER_API_KEY en el archivo .env")
        return OpenAICompatibleProvider(
            provider_id="openrouter",
            model=model,
            base_url="https://openrouter.ai/api/v1",
            api_key=key,
        )
    if pid == "deepseek":
        key = os.getenv("DEEPSEEK_API_KEY")
        if not key:
            raise ValueError("Falta DEEPSEEK_API_KEY en el archivo .env")
        return OpenAICompatibleProvider(
            provider_id="deepseek",
            model=model,
            base_url="https://api.deepseek.com/v1",
            api_key=key,
        )
    if pid == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        return OpenAICompatibleProvider(
            provider_id="ollama",
            model=model,
            base_url=base_url,
            api_key="ollama",
        )
    raise ValueError(f"Proveedor desconocido: '{provider_id}'. Soportados: google, groq, openrouter, deepseek, ollama.")
