from dataclasses import dataclass
from pathlib import Path

from backend.agents.engine import AgentEngine
from backend.agents.orchestrator import MultiAgentOrchestrator
from backend.agents.registry import AgentRegistry
from backend.agents.schemas import AgentConfig
from backend.api.ws import SessionConnectionManager
from backend.core.events import EventBus
from backend.providers.google import GoogleProvider
from backend.storage.database import Database
from backend.storage.repository import StorageRepository
from backend.tools.blackboard import ReadBlackboardTool, WriteBlackboardTool
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


def build_container(db_path: str | Path = "data/agent_lab.db") -> AppContainer:
    db = Database(db_path)
    db.initialize()
    repo = StorageRepository(db)
    events = EventBus()
    ws_manager = SessionConnectionManager()
    events.subscribe("*", ws_manager.broadcast_event)

    agents = AgentRegistry()
    agents.register(
        AgentConfig(
            id="explorador",
            name="Agente Explorador",
            role="Analista de Workspace",
            system_prompt=(
                "Eres el Agente Explorador de AGENT LAB. "
                "Usa list_files, read_file y write_blackboard para analizar el workspace y compartir tus hallazgos."
            ),
            allowed_tools=("list_files", "read_file", "read_blackboard", "write_blackboard"),
            max_steps=8,
        )
    )
    agents.register(
        AgentConfig(
            id="programador",
            name="Agente Programador",
            role="Desarrollador de Software",
            system_prompt=(
                "Eres un programador experto en AGENT LAB. "
                "Consulta read_blackboard y el workspace antes de crear o editar código."
            ),
            allowed_tools=(
                "list_files",
                "read_file",
                "write_file",
                "edit_file",
                "read_blackboard",
                "write_blackboard",
            ),
            max_steps=10,
        )
    )

    tools = ToolRegistry()
    tools.register(ListFilesTool())
    tools.register(ReadFileTool())
    tools.register(WriteFileTool())
    tools.register(EditFileTool())
    tools.register(ReadBlackboardTool(repo))
    tools.register(WriteBlackboardTool(repo))

    engine = AgentEngine(
        agent_registry=agents,
        tool_registry=tools,
        repository=repo,
        event_bus=events,
        provider_factory=lambda route: GoogleProvider(model=route.model),
    )
    orchestrator = MultiAgentOrchestrator(
        engine=engine,
        repository=repo,
        event_bus=events,
    )

    return AppContainer(
        db=db,
        repo=repo,
        events=events,
        ws_manager=ws_manager,
        agents=agents,
        tools=tools,
        engine=engine,
        orchestrator=orchestrator,
    )
