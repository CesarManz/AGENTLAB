from backend.tools.git_ops import GitDiffTool, GitStatusTool
from dataclasses import dataclass
from pathlib import Path

from backend.agents.engine import AgentEngine
from backend.agents.orchestrator import MultiAgentOrchestrator
from backend.agents.planner import TaskPlanner
from backend.agents.registry import AgentRegistry
from backend.agents.schemas import AgentConfig
from backend.api.ws import SessionConnectionManager
from backend.core.config import ModelRoute
from backend.core.events import EventBus
from backend.core.skills import SkillRegistry
from backend.providers.base import BaseProvider
from backend.providers.google import GoogleProvider
from backend.providers.openai_compat import build_openai_compatible_provider
from backend.storage.database import Database
from backend.storage.repository import StorageRepository
from backend.tools.blackboard import ReadBlackboardTool, WriteBlackboardTool
from backend.tools.execution import RunPytestTool
from backend.tools.knowledge_graph import QueryCodeGraphTool
from backend.tools.filesystem import EditFileTool, ListFilesTool, ReadFileTool, WriteFileTool
from backend.tools.registry import ToolRegistry


@dataclass
class AppContainer:
    db: Database
    repo: StorageRepository
    events: EventBus
    ws_manager: SessionConnectionManager
    agents: AgentRegistry
    tools: ToolRegistry
    engine: AgentEngine
    orchestrator: MultiAgentOrchestrator
    planner: TaskPlanner
    skills: SkillRegistry | None = None


def create_provider_for_route(route: ModelRoute) -> BaseProvider:
    if route.provider == "google":
        return GoogleProvider(model=route.model)
    return build_openai_compatible_provider(route.provider, route.model)


def build_container(db_path: str | Path = "data/agent_lab.db") -> AppContainer:
    db = Database(db_path)
    db.initialize()
    repo = StorageRepository(db)
    events = EventBus()
    ws_manager = SessionConnectionManager()
    events.subscribe("*", ws_manager.broadcast_event)

    skills = SkillRegistry()
    skills.load_from_directory()

    agents = AgentRegistry()
    agents.register(
        AgentConfig(
            id="explorador",
            name="Agente Explorador",
            role="Analista de Repositorio",
            model_tier="fast",
            system_prompt=(
                "Eres el Agente Explorador de AGENT LAB. "
                "Usa list_files, read_file y write_blackboard para mapear la estructura del workspace y compartir hallazgos claros."
            ),
            allowed_tools=("list_files", "read_file", "query_code_graph", "git_status", "git_diff", "run_pytest", "read_blackboard", "write_blackboard"),
            default_skills=("security_audit",),
            max_steps=8,
        )
    )
    agents.register(
        AgentConfig(
            id="programador",
            name="Agente Programador",
            role="Ingeniero de Software",
            model_tier="balanced",
            system_prompt=(
                "Eres un ingeniero de software experto en AGENT LAB. "
                "Revisa read_blackboard y los archivos existentes antes de escribir o modificar código limpio y tipado."
            ),
            allowed_tools=(
                "list_files",
                "read_file",
                "write_file",
                "edit_file",
                "run_pytest",
                "read_blackboard",
                "write_blackboard",
            ),
            max_steps=10,
        )
    )
    agents.register(
        AgentConfig(
            id="revisor",
            name="Agente Revisor",
            role="Auditor de Calidad y Seguridad",
            model_tier="reasoning",
            system_prompt=(
                "Eres el Auditor Técnico de AGENT LAB. "
                "Inspecciona el código generado en el workspace, detecta bugs, problemas de seguridad o casos borde, "
                "y publica tu veredicto técnico en write_blackboard bajo 'revision'."
            ),
            allowed_tools=("list_files", "read_file", "query_code_graph", "git_status", "git_diff", "run_pytest", "read_blackboard", "write_blackboard"),
            default_skills=("security_audit",),
            max_steps=8,
        )
    )

    tools = ToolRegistry()
    tools.register(ListFilesTool())
    tools.register(ReadFileTool())
    tools.register(WriteFileTool())
    tools.register(EditFileTool())
    tools.register(RunPytestTool())
    tools.register(QueryCodeGraphTool())
    tools.register(GitStatusTool())
    tools.register(GitDiffTool())
    tools.register(ReadBlackboardTool(repo))
    tools.register(WriteBlackboardTool(repo))

    engine = AgentEngine(
        agent_registry=agents,
        tool_registry=tools,
        repository=repo,
        event_bus=events,
        provider_factory=create_provider_for_route,
        skill_registry=skills,
    )
    orchestrator = MultiAgentOrchestrator(
        engine=engine,
        repository=repo,
        event_bus=events,
    )
    planner = TaskPlanner(
        agent_registry=agents,
        repository=repo,
        provider_factory=create_provider_for_route,
    )

    return AppContainer(
        db=db,
        repo=repo,
        events=events,
        ws_manager=ws_manager,
        agents=agents,
        skills=skills,
        tools=tools,
        engine=engine,
        orchestrator=orchestrator,
        planner=planner,
    )

