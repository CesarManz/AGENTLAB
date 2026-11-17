from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.agents.engine import AgentEngine
from backend.agents.registry import AgentRegistry
from backend.agents.schemas import AgentConfig
from backend.api.dependencies import AppContainer
from backend.api.main import create_app
from backend.core.events import EventBus
from backend.providers.base import BaseProvider
from backend.providers.schemas import LLMResponse, Message, TokenUsage, ToolCall, ToolDefinition
from backend.storage.database import Database
from backend.storage.repository import StorageRepository
from backend.tools.filesystem import EditFileTool, ListFilesTool, ReadFileTool, WriteFileTool
from backend.tools.registry import ToolRegistry


class ScriptedMockProvider(BaseProvider):
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


def _build_test_client(tmp_path: Path, responses: list[LLMResponse]) -> tuple[TestClient, Path]:
    ws = tmp_path / "workspace"
    ws.mkdir()

    db = Database(tmp_path / "api_test.db")
    db.initialize()
    repo = StorageRepository(db)
    events = EventBus()

    agents = AgentRegistry()
    agents.register(
        AgentConfig(
            id="programador",
            name="Programador",
            role="Dev",
            system_prompt="Eres un programador.",
            allowed_tools=("list_files", "read_file", "write_file", "edit_file"),
            max_steps=5,
        )
    )

    tools = ToolRegistry()
    tools.register(ListFilesTool())
    tools.register(ReadFileTool())
    tools.register(WriteFileTool())
    tools.register(EditFileTool())

    provider = ScriptedMockProvider(responses)
    engine = AgentEngine(
        agent_registry=agents,
        tool_registry=tools,
        repository=repo,
        event_bus=events,
        provider_factory=lambda route: provider,
    )

    app = create_app(db_path=tmp_path / "api_test.db")
    app.state.container = AppContainer(
        db=db, repo=repo, events=events, agents=agents, tools=tools, engine=engine
    )
    return TestClient(app), ws


def test_api_hitl_approve_flow(tmp_path: Path) -> None:
    responses = [
        LLMResponse(
            content=None,
            tool_calls=(
                ToolCall(
                    id="call_write_1",
                    tool_name="write_file",
                    arguments={"path": "config.py", "content": "DEBUG = True\n"},
                ),
            ),
            usage=TokenUsage(input_tokens=40, output_tokens=20, total_tokens=60),
            provider="mock",
            model_name="mock-v1",
            finish_reason="tool_calls",
            latency_ms=10,
        ),
        LLMResponse(
            content="Archivo config.py creado correctamente.",
            usage=TokenUsage(input_tokens=60, output_tokens=15, total_tokens=75),
            provider="mock",
            model_name="mock-v1",
            finish_reason="stop",
            latency_ms=8,
        ),
    ]
    client, ws = _build_test_client(tmp_path, responses)

    res1 = client.post(
        "/sessions",
        json={
            "agent_id": "programador",
            "user_prompt": "Crea config.py",
            "workspace_path": str(ws),
        },
    )
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["run"]["status"] == "awaiting_approval"
    assert len(data1["pending_approvals"]) == 1
    assert not (ws / "config.py").exists()

    exec_id = data1["pending_approvals"][0]["id"]
    res2 = client.post(f"/approvals/{exec_id}", json={"approved": True})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["run"]["status"] == "completed"
    assert data2["pending_approvals"] == []
    assert (ws / "config.py").read_text(encoding="utf-8") == "DEBUG = True\n"
    assert data2["session"]["total_tokens_used"] == 135


def test_api_hitl_reject_flow(tmp_path: Path) -> None:
    responses = [
        LLMResponse(
            content=None,
            tool_calls=(
                ToolCall(
                    id="call_write_reject",
                    tool_name="write_file",
                    arguments={"path": "peligro.py", "content": "import os\n"},
                ),
            ),
            usage=TokenUsage(input_tokens=30, output_tokens=15, total_tokens=45),
            provider="mock",
            model_name="mock-v1",
            finish_reason="tool_calls",
            latency_ms=5,
        ),
        LLMResponse(
            content="Entendido, no crearé el archivo.",
            usage=TokenUsage(input_tokens=50, output_tokens=10, total_tokens=60),
            provider="mock",
            model_name="mock-v1",
            finish_reason="stop",
            latency_ms=5,
        ),
    ]
    client, ws = _build_test_client(tmp_path, responses)

    res1 = client.post(
        "/sessions",
        json={
            "agent_id": "programador",
            "user_prompt": "Crea peligro.py",
            "workspace_path": str(ws),
        },
    )
    exec_id = res1.json()["pending_approvals"][0]["id"]

    res2 = client.post(f"/approvals/{exec_id}", json={"approved": False})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["run"]["status"] == "completed"
    assert not (ws / "peligro.py").exists()
    assert "no crearé" in data2["run"]["result_summary"]
