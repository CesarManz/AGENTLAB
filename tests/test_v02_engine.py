import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from backend.agents.engine import AgentEngine
from backend.agents.registry import AgentRegistry
from backend.agents.schemas import AgentConfig, TaskSession
from backend.core.events import EventBus
from backend.providers.base import BaseProvider
from backend.providers.schemas import LLMResponse, Message, TokenUsage, ToolCall, ToolDefinition
from backend.storage.database import Database
from backend.storage.repository import StorageRepository
from backend.tools.filesystem import ListFilesTool, ReadFileTool
from backend.tools.registry import ToolRegistry


class ScriptedMockProvider(BaseProvider):
    """Proveedor determinista en memoria para probar el AgentEngine sin red."""

    def __init__(self, scripted_responses: list[LLMResponse]) -> None:
        self._responses = list(scripted_responses)
        self.calls_count = 0

    @property
    def provider_name(self) -> str:
        return "mock"

    async def generate(
        self,
        messages: Sequence[Message],
        *,
        system_instruction: str | None = None,
        tools: Sequence[ToolDefinition] | None = None,
        temperature: float = 0.2,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        idx = min(self.calls_count, len(self._responses) - 1)
        self.calls_count += 1
        return self._responses[idx]


def _setup_env(tmp_path: Path, provider: BaseProvider, max_steps: int = 5):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "readme.txt").write_text("Contenido secreto del proyecto", encoding="utf-8")

    db = Database(tmp_path / "test.db")
    db.initialize()
    repo = StorageRepository(db)
    bus = EventBus()

    agent_reg = AgentRegistry()
    agent_reg.register(
        AgentConfig(
            id="tester",
            name="Tester",
            role="QA",
            system_prompt="Eres un agente de prueba.",
            allowed_tools=("list_files", "read_file"),
            max_steps=max_steps,
        )
    )

    tool_reg = ToolRegistry()
    tool_reg.register(ListFilesTool())
    tool_reg.register(ReadFileTool())

    engine = AgentEngine(
        agent_registry=agent_reg,
        tool_registry=tool_reg,
        repository=repo,
        event_bus=bus,
        provider_factory=lambda route: provider,
    )
    return engine, repo, ws


def test_end_to_end_tool_loop_and_ledger(tmp_path: Path) -> None:
    provider = ScriptedMockProvider(
        [
            LLMResponse(
                content=None,
                tool_calls=(
                    ToolCall(id="c1", tool_name="read_file", arguments={"path": "readme.txt"}),
                ),
                usage=TokenUsage(input_tokens=50, output_tokens=20, total_tokens=70),
                provider="mock",
                model_name="mock-v1",
                finish_reason="tool_calls",
                latency_ms=10,
            ),
            LLMResponse(
                content="Resumen completado con éxito.",
                usage=TokenUsage(input_tokens=80, output_tokens=30, total_tokens=110),
                provider="mock",
                model_name="mock-v1",
                finish_reason="stop",
                latency_ms=12,
            ),
        ]
    )
    engine, repo, ws = _setup_env(tmp_path, provider)
    session = TaskSession(user_prompt="Lee readme.txt", workspace_path=str(ws), max_budget_tokens=500)

    run = asyncio.run(engine.execute_session(session, "tester"))
    saved = repo.get_session(session.id)

    assert run.status == "completed"
    assert run.current_step == 2
    assert run.result_summary == "Resumen completado con éxito."
    assert saved is not None
    assert saved.total_tokens_used == 180


def test_budget_limit_stops_execution(tmp_path: Path) -> None:
    provider = ScriptedMockProvider(
        [
            LLMResponse(
                content=None,
                tool_calls=(
                    ToolCall(id="c1", tool_name="list_files", arguments={}),
                ),
                usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
                provider="mock",
                model_name="mock-v1",
                finish_reason="tool_calls",
                latency_ms=5,
            ),
            LLMResponse(
                content="Nunca debería llegar aquí",
                usage=TokenUsage(input_tokens=10, output_tokens=10, total_tokens=20),
                provider="mock",
                model_name="mock-v1",
                finish_reason="stop",
                latency_ms=5,
            ),
        ]
    )
    engine, repo, ws = _setup_env(tmp_path, provider)
    session = TaskSession(user_prompt="Lista archivos", workspace_path=str(ws), max_budget_tokens=100)

    run = asyncio.run(engine.execute_session(session, "tester"))
    assert run.status == "failed"
    assert "Presupuesto máximo" in (run.error_message or "")
    assert provider.calls_count == 1


def test_max_steps_prevents_infinite_loop(tmp_path: Path) -> None:
    infinite_tool_call = LLMResponse(
        content=None,
        tool_calls=(ToolCall(id="loop", tool_name="list_files", arguments={}),),
        usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        provider="mock",
        model_name="mock-v1",
        finish_reason="tool_calls",
        latency_ms=2,
    )
    provider = ScriptedMockProvider([infinite_tool_call])
    engine, _, ws = _setup_env(tmp_path, provider, max_steps=3)
    session = TaskSession(user_prompt="Bucle", workspace_path=str(ws), max_budget_tokens=10_000)

    run = asyncio.run(engine.execute_session(session, "tester"))
    assert run.status == "failed"
    assert "límite máximo de 3 pasos" in (run.error_message or "")
    assert provider.calls_count == 3
