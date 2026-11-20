from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.agents.engine import AgentEngine
from backend.agents.orchestrator import MultiAgentOrchestrator
from backend.agents.planner import TaskPlanner
from backend.agents.registry import AgentRegistry
from backend.agents.schemas import AgentConfig
from backend.api.dependencies import AppContainer
from backend.api.main import create_app
from backend.api.ws import SessionConnectionManager
from backend.core.events import EventBus
from backend.core.skills import SkillRegistry
from backend.providers.base import BaseProvider
from backend.providers.schemas import LLMResponse, Message, TokenUsage, ToolCall, ToolDefinition
from backend.storage.database import Database
from backend.storage.repository import StorageRepository
from backend.tools.filesystem import EditFileTool, ReadFileTool, WriteFileTool
from backend.tools.git_ops import build_hitl_file_preview
from backend.tools.registry import ToolRegistry


class _FakeEditProvider(BaseProvider):
    def __init__(self, script: list[LLMResponse]) -> None:
        self._script = list(script)

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
        if not self._script:
            return LLMResponse(
                content="Listo.",
                tool_calls=[],
                usage=TokenUsage(input_tokens=5, output_tokens=5),
                provider="mock",
                model_name="mock-fast",
                finish_reason="stop",
                latency_ms=1,
            )
        return self._script.pop(0)


def test_build_hitl_file_preview_generates_unified_diff_for_new_and_edited_files(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    # 1. Archivo nuevo
    diff_new, sha_new = build_hitl_file_preview(
        ws, "write_file", {"path": "calc.py", "content": "def suma(a, b):\n    return a + b\n"}
    )
    assert sha_new == "__MISSING__"
    assert diff_new is not None
    assert "--- /dev/null" in diff_new
    assert "+++ b/calc.py" in diff_new
    assert "+def suma(a, b):" in diff_new

    # 2. Edición parcial sobre archivo existente
    (ws / "calc.py").write_text("def suma(a, b):\n    return a + b\n", encoding="utf-8")
    diff_edit, sha_edit = build_hitl_file_preview(
        ws,
        "edit_file",
        {"path": "calc.py", "old_text": "return a + b", "new_text": "return int(a + b)"},
    )
    assert sha_edit is not None and sha_edit != "__MISSING__"
    assert diff_edit is not None
    assert "-    return a + b" in diff_edit
    assert "+    return int(a + b)" in diff_edit


def test_hitl_approval_blocks_execution_when_file_changed_on_disk_after_preview(tmp_path: Path) -> None:
    ws = tmp_path / "ws_conflict"
    ws.mkdir()
    target = ws / "config.py"
    target.write_text("DEBUG = False\n", encoding="utf-8")

    db = Database(tmp_path / "test.db")
    db.initialize()
    repo = StorageRepository(db)
    events = EventBus()
    ws_manager = SessionConnectionManager()
    skills = SkillRegistry(tmp_path / "skills_empty")

    tools = ToolRegistry()
    tools.register(ReadFileTool())
    tools.register(WriteFileTool())
    tools.register(EditFileTool())

    agents = AgentRegistry()
    agents.register(
        AgentConfig(
            id="coder_test",
            name="Coder Test",
            role="Coder",
            system_prompt="Edita archivos.",
            allowed_tools=("read_file", "edit_file"),
        )
    )

    fake = _FakeEditProvider(
        [
            LLMResponse(
                content="Voy a activar DEBUG.",
                tool_calls=[
                    ToolCall(
                        id="tc_edit_1",
                        tool_name="edit_file",
                        arguments={"path": "config.py", "old_text": "DEBUG = False", "new_text": "DEBUG = True"},
                    )
                ],
                usage=TokenUsage(input_tokens=10, output_tokens=10),
                provider="mock",
                model_name="mock-fast",
                finish_reason="stop",
                latency_ms=1,
            ),
            LLMResponse(
                content="No se pudo aplicar por conflicto.",
                tool_calls=[],
                usage=TokenUsage(input_tokens=10, output_tokens=10),
                provider="mock",
                model_name="mock-fast",
                finish_reason="stop",
                latency_ms=1,
            ),
        ]
    )

    engine = AgentEngine(
        agent_registry=agents,
        tool_registry=tools,
        repository=repo,
        event_bus=events,
        provider_factory=lambda route: fake,
        skill_registry=skills,
    )
    orchestrator = MultiAgentOrchestrator(engine=engine, repository=repo, event_bus=events)
    planner = TaskPlanner(agent_registry=agents, repository=repo, provider_factory=lambda route: fake)

    app = create_app(db_path=tmp_path / "test.db")
    app.state.container = AppContainer(
        db=db,
        repo=repo,
        events=events,
        ws_manager=ws_manager,
        agents=agents,
        tools=tools,
        skills=skills,
        engine=engine,
        orchestrator=orchestrator,
        planner=planner,
    )

    with TestClient(app) as client:
        res = client.post(
            "/sessions",
            json={
                "user_prompt": "Activa DEBUG",
                "agent_id": "coder_test",
                "workspace_path": str(ws),
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["session"]["status"] == "awaiting_approval"
        pending = data["pending_approvals"][0]
        assert "-DEBUG = False" in pending["diff_preview"]
        assert "+DEBUG = True" in pending["diff_preview"]

        # Mientras espera aprobación, el usuario modifica config.py manualmente
        target.write_text("DEBUG = False\nSECRET_MODE = 'manual'\n", encoding="utf-8")

        # Al aprobar, el motor detecta el cambio de SHA-256 y bloquea la escritura
        app_res = client.post(f"/approvals/{pending['id']}", json={"approved": True})
        assert app_res.status_code == 200
        assert target.read_text(encoding="utf-8") == "DEBUG = False\nSECRET_MODE = 'manual'\n"