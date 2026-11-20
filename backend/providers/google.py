import asyncio
import base64
import json
import os
import time
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.providers.base import BaseProvider
from backend.providers.schemas import (
    LLMResponse,
    Message,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)

load_dotenv()

TRANSIENT_MARKERS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL")


class GoogleProvider(BaseProvider):
    """
    Adaptador para modelos Gemini mediante el SDK oficial google-genai,
    con reintentos automáticos ante errores transitorios (503/429).
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        max_retries: int = 3,
    ) -> None:
        self.model = model
        self.max_retries = max_retries
        resolved_key = api_key or os.getenv("GEMINI_API_KEY")

        if not resolved_key:
            raise ValueError("No se encontró GEMINI_API_KEY en el entorno.")

        self._client = genai.Client(api_key=resolved_key)
        self._async_client = self._client.aio

    @property
    def provider_name(self) -> str:
        return "google"

    def _to_genai_contents(self, messages: Sequence[Message]) -> list[types.Content]:
        """
        Convierte la secuencia de Message agnósticos en objetos types.Content de Gemini.
        """
        contents: list[types.Content] = []
        pending_tool_parts: list[types.Part] = []

        def flush_tool_parts() -> None:
            if pending_tool_parts:
                contents.append(
                    types.Content(role="user", parts=list(pending_tool_parts))
                )
                pending_tool_parts.clear()

        for msg in messages:
            if msg.role == "tool":
                pending_tool_parts.append(
                    types.Part.from_function_response(
                        name=msg.tool_name or "unknown_tool",
                        response={"result": msg.content or ""},
                    )
                )
                continue

            flush_tool_parts()

            if msg.role == "user":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=msg.content or "")],
                    )
                )
            elif msg.role == "assistant":
                parts: list[types.Part] = []
                if msg.content:
                    parts.append(types.Part.from_text(text=msg.content))
                for tc in msg.tool_calls:
                    sig_b64 = tc.provider_metadata.get("thought_signature_b64")
                    sig_bytes = base64.b64decode(sig_b64) if sig_b64 else None
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                name=tc.tool_name,
                                args=tc.arguments,
                            ),
                            thought_signature=sig_bytes,
                        )
                    )
                if parts:
                    contents.append(types.Content(role="model", parts=parts))

        flush_tool_parts()
        return contents

    def _to_genai_tools(
        self, tools: Sequence[ToolDefinition] | None
    ) -> list[types.Tool] | None:
        if not tools:
            return None

        declarations = [
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.json_schema,
            )
            for tool in tools
        ]
        return [types.Tool(function_declarations=declarations)]

    def _map_finish_reason(
        self, candidate: Any, has_tool_calls: bool
    ) -> str:
        if has_tool_calls:
            return "tool_calls"

        raw_reason = str(getattr(candidate, "finish_reason", "") or "").upper()
        if "MAX_TOKENS" in raw_reason:
            return "max_tokens"
        if "SAFETY" in raw_reason or "RECITATION" in raw_reason:
            return "safety"
        return "stop"

    def _is_transient_error(self, exc: Exception) -> bool:
        msg = str(exc).upper()
        return any(marker in msg for marker in TRANSIENT_MARKERS)

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

        config_kwargs: dict[str, Any] = {
            "temperature": temperature,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        genai_tools = self._to_genai_tools(tools)
        if genai_tools:
            config_kwargs["tools"] = genai_tools

        if response_schema:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = response_schema

        config = types.GenerateContentConfig(**config_kwargs)
        contents = self._to_genai_contents(messages)

        response: Any = None
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self._async_client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_retries and self._is_transient_error(exc):
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                break

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        if last_exc is not None or response is None:
            return LLMResponse(
                content=f"Error al invocar proveedor Google: {last_exc}",
                provider=self.provider_name,
                model_name=self.model,
                finish_reason="error",
                latency_ms=elapsed_ms,
            )

        text_parts: list[str] = []
        extracted_tool_calls: list[ToolCall] = []

        candidates = getattr(response, "candidates", None) or []
        first_candidate = candidates[0] if candidates else None
        content_obj = getattr(first_candidate, "content", None)
        parts = getattr(content_obj, "parts", None) or []

        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                text_parts.append(part_text)

            fn_call = getattr(part, "function_call", None)
            if fn_call and getattr(fn_call, "name", None):
                raw_args = getattr(fn_call, "args", None) or {}
                call_id = getattr(fn_call, "id", None) or f"call_{uuid4().hex[:12]}"

                meta: dict[str, Any] = {}
                thought_sig = getattr(part, "thought_signature", None)
                if isinstance(thought_sig, bytes):
                    meta["thought_signature_b64"] = base64.b64encode(thought_sig).decode("ascii")

                extracted_tool_calls.append(
                    ToolCall(
                        id=call_id,
                        tool_name=fn_call.name,
                        arguments=dict(raw_args),
                        provider_metadata=meta,
                    )
                )

        full_text = "\n".join(text_parts) if text_parts else None

        parsed_output: dict[str, Any] | None = None
        if response_schema and full_text:
            try:
                loaded = json.loads(full_text)
                if isinstance(loaded, dict):
                    parsed_output = loaded
            except json.JSONDecodeError:
                parsed_output = None

        usage_meta = getattr(response, "usage_metadata", None)
        usage = TokenUsage(
            input_tokens=getattr(usage_meta, "prompt_token_count", None),
            output_tokens=getattr(usage_meta, "candidates_token_count", None),
            cached_tokens=getattr(usage_meta, "cached_content_token_count", None),
            total_tokens=getattr(usage_meta, "total_token_count", None),
        )

        finish_reason = self._map_finish_reason(
            first_candidate, has_tool_calls=len(extracted_tool_calls) > 0
        )

        return LLMResponse(
            content=full_text,
            parsed_output=parsed_output,
            tool_calls=tuple(extracted_tool_calls),
            usage=usage,
            provider=self.provider_name,
            model_name=self.model,
            finish_reason=finish_reason,  # type: ignore[arg-type]
            latency_ms=elapsed_ms,
        )

    async def close(self) -> None:
        await self._async_client.aclose()
        self._client.close()
