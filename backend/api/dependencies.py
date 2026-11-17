from dataclasses import dataclass
from pathlib import Path

from backend.agents.engine import AgentEngine
from backend.agents.registry import AgentRegistry
from backend.agents.schemas import AgentConfig
from backend.core.events import EventBus
from backend.providers.google import GoogleProvider
from backend.storage.database import Database
from backend.storage.repository import StorageRepository
from backend.tools.filesystem import EditFileTool, ListFilesTool, ReadFileTool, WriteFileTool
from backend.tools.registry import ToolRegistry


@dataclass
class AppContainer:
    db: Database
    repo: StorageRepository
    events: EventBus
    agents: AgentRegistry
    tools: ToolRegistry
    engine: AgentEngine


def build_container(db_path: str | Path = "data/agent_lab.db") -> AppContainer:
    db = Database(db_path)
    db.initialize()
    repo = StorageRepository(db)
    events = EventBus()

    agents = AgentRegistry()
    agents.register(
        AgentConfig(
            id="explorador",
            name="Agente Explorador",
            role="Analista de Workspace",
            system_prompt=(
                "Eres el Agente Explorador de AGENT LAB. "
                "Usa list_files y read_file para analizar el workspace y responder con precisión."
            ),
            allowed_tools=("list_files", "read_file"),
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
                "Inspecciona el workspace antes de modificar archivos y usa write_file o edit_file con código limpio."
            ),
            allowed_tools=("list_files", "read_file", "write_file", "edit_file"),
            max_steps=10,
        )
    )

    tools = ToolRegistry()
    tools.register(ListFilesTool())
    tools.register(ReadFileTool())
    tools.register(WriteFileTool())
    tools.register(EditFileTool())

    engine = AgentEngine(
        agent_registry=agents,
        tool_registry=tools,
        repository=repo,
        event_bus=events,
        provider_factory=lambda route: GoogleProvider(model=route.model),
    )

    return AppContainer(
        db=db,
        repo=repo,
        events=events,
        agents=agents,
        tools=tools,
        engine=engine,
    )
