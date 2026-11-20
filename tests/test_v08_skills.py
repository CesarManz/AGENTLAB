import asyncio
from pathlib import Path

from backend.agents.engine import AgentEngine
from backend.agents.registry import AgentRegistry
from backend.agents.schemas import AgentConfig, TaskSession
from backend.core.events import EventBus
from backend.core.skills import SkillRegistry
from backend.providers.base import BaseProvider
from backend.providers.schemas import LLMResponse, TokenUsage
from backend.storage.database import Database
from backend.storage.repository import StorageRepository
from backend.tools.registry import ToolRegistry


def test_skill_registry_injects_triggered_skills_into_system_prompt(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "tdd.md").write_text(
        "---\nid: tdd\nname: TDD Protocol\ntriggers: pytest, prueba\n---\nSiempre usa asserts claros.",
        encoding="utf-8",
    )

    registry = SkillRegistry(skills_dir)
    assert registry.load_from_directory() == 1

    captured_prompts: list[str] = []

    class InspectingProvider(BaseProvider):
        @property
        def provider_name(self) -> str:
            return "mock"

        async def generate(self, messages, *, system_instruction=None, **kwargs) -> LLMResponse:
            captured_prompts.append(system_instruction or "")
            return LLMResponse(
                content="Hecho.",
                usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
                provider="mock",
                model_name="mock-v1",
                finish_reason="stop",
                latency_ms=5,
            )

    db = Database(tmp_path / "skills_test.db")
    db.initialize()
    repo = StorageRepository(db)
    agents = AgentRegistry()
    agents.register(
        AgentConfig(
            id="dev",
            name="Dev",
            role="Dev",
            system_prompt="Prompt base.",
        )
    )

    provider = InspectingProvider()
    engine = AgentEngine(
        agent_registry=agents,
        tool_registry=ToolRegistry(),
        repository=repo,
        event_bus=EventBus(),
        provider_factory=lambda route: provider,
        skill_registry=registry,
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    session = TaskSession(user_prompt="Crea pruebas con pytest", workspace_path=str(ws))
    repo.create_session(session)

    run = asyncio.run(
        engine.execute_agent_in_session(
            session=session,
            agent_id="dev",
            task_instruction="Escribe pruebas unitarias con pytest",
        )
    )

    assert run.active_skills == ["tdd"]
    assert len(captured_prompts) == 1
    assert "Prompt base." in captured_prompts[0]
    assert "TDD Protocol" in captured_prompts[0]
    assert "Siempre usa asserts claros." in captured_prompts[0]