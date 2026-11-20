import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.agents.engine import AgentEngine
from backend.agents.orchestrator import MultiAgentOrchestrator
from backend.agents.planner import TaskPlanner
from backend.agents.registry import AgentRegistry
from backend.agents.schemas import AgentConfig, AgentRun, TaskSession
from backend.api.dependencies import AppContainer
from backend.api.main import create_app
from backend.api.ws import SessionConnectionManager
from backend.core.events import EventBus
from backend.core.skills import SkillRegistry
from backend.providers.base import BaseProvider
from backend.providers.schemas import LLMResponse, Message, TokenUsage, ToolDefinition
from backend.storage.database import Database
from backend.storage.repository import StorageRepository
from backend.tools.execution import RunPytestArgs, RunPytestTool
from backend.tools.filesystem import ListFilesTool, ReadFileTool
from backend.tools.registry import ToolRegistry


class _StaticMockProvider(BaseProvider):
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
        return LLMResponse(
            content="Etapa recuperada y completada.",
            tool_calls=[],
            usage=TokenUsage(input_tokens=8, output_tokens=8),
            provider="mock",
            model_name="mock-fast",
            finish_reason="stop",
            latency_ms=1,
        )


def test_run_pytest_executes_with_restricted_env_hiding_api_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "super-secret-groq-key")
    monkeypatch.setenv("CUSTOM_AUTH_TOKEN", "secret-token-123")

    ws = tmp_path / "ws_env"
    ws.mkdir()
    test_file = ws / "test_env_leak.py"
    test_file.write_text(
        "import os\n"
        "def test_secrets_are_stripped():\n"
        "    assert os.environ.get('AGENTLAB_RESTRICTED_ENV') == '1'\n"
        "    assert 'GEMINI_API_KEY' not in os.environ\n"
        "    assert 'GROQ_API_KEY' not in os.environ\n"
        "    assert 'CUSTOM_AUTH_TOKEN' not in os.environ\n",
        encoding="utf-8",
    )

    tool = RunPytestTool()
    res = asyncio.run(tool.execute("tc_env_1", RunPytestArgs(target_path="test_env_leak.py"), ws))
    assert res.status == "success", res.output
    assert "1 passed" in res.output


def test_startup_crash_recovery_marks_running_sessions_interrupted_and_resumes_idempotently(tmp_path: Path) -> None:
    ws = tmp_path / "ws_recovery"
    ws.mkdir()

    db_path = tmp_path / "recovery.db"
    db = Database(db_path)
    db.initialize()
    repo = StorageRepository(db)

    # Simular sesión de 2 etapas que quedó colgada en 'running' en la etapa 1 tras caída del servidor
    crashed_session = TaskSession(
        user_prompt="Construir módulo",
        status="running",
        workspace_path=str(ws),
        blackboard={"stage_0_done": True},
        pipeline_stages=[
            {"node_id": "step_1", "agent_id": "explorador", "instruction": "Explorar"},
            {"node_id": "step_2", "agent_id": "programador", "instruction": "Implementar"},
        ],
        current_stage_index=1,
    )
    repo.create_session(crashed_session)
    repo.create_run(
        AgentRun(
            session_id=crashed_session.id,
            dag_node_id="step_2",
            agent_id="programador",
            task_instruction="Implementar",
            status="running",
        )
    )

    events = EventBus()
    ws_manager = SessionConnectionManager()
    skills = SkillRegistry(tmp_path / "skills_empty")
    tools = ToolRegistry()
    tools.register(ListFilesTool())
    tools.register(ReadFileTool())

    agents = AgentRegistry()
    agents.register(
        AgentConfig(
            id="explorador",
            name="Explorador",
            role="Analista",
            system_prompt="Explora.",
            allowed_tools=("list_files",),
        )
    )
    agents.register(
        AgentConfig(
            id="programador",
            name="Programador",
            role="Dev",
            system_prompt="Programa.",
            allowed_tools=("list_files", "read_file"),
        )
    )

    provider = _StaticMockProvider()
    engine = AgentEngine(
        agent_registry=agents,
        tool_registry=tools,
        repository=repo,
        event_bus=events,
        provider_factory=lambda route: provider,
        skill_registry=skills,
    )
    orchestrator = MultiAgentOrchestrator(engine=engine, repository=repo, event_bus=events)
    planner = TaskPlanner(agent_registry=agents, repository=repo, provider_factory=lambda route: provider)

    app = create_app(db_path=db_path)
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

    # Al entrar en TestClient se ejecuta lifespan() -> reconcilia 'running' a 'interrupted'
    with TestClient(app) as client:
        sess_res = client.get(f"/sessions/{crashed_session.id}")
        assert sess_res.status_code == 200
        assert sess_res.json()["session"]["status"] == "interrupted"

        # Reanudar desde stage_index=1 (no repite stage_index=0)
        resume_1 = client.post(f"/sessions/{crashed_session.id}/resume")
        assert resume_1.status_code == 200
        assert resume_1.json()["session"]["status"] == "completed"
        assert resume_1.json()["session"]["blackboard"]["stage_0_done"] is True

        # Llamar resume por segunda vez es idempotente y no crea nuevas ejecuciones
        runs_after_first = len(repo.list_runs_for_session(crashed_session.id))
        resume_2 = client.post(f"/sessions/{crashed_session.id}/resume")
        assert resume_2.status_code == 200
        assert len(repo.list_runs_for_session(crashed_session.id)) == runs_after_first