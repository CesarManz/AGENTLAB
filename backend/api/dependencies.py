from typing import Any
import asyncio
from dataclasses import dataclass, field
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
from backend.tools.filesystem import EditFileTool, ListFilesTool, ReadFileTool, WriteFileTool
from backend.tools.git_ops import GitDiffTool, GitStatusTool
from backend.tools.knowledge_graph import QueryCodeGraphTool
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
    running_tasks: dict[str, asyncio.Task[Any]] = field(default_factory=dict)


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
            id="arquitecto",
            name="Agente Arquitecto",
            role="Diseño de Sistemas y Estructura",
            description="Diseña la arquitectura, módulos, contratos de datos y plan técnico antes de programar.",
            model_tier="reasoning",
            system_prompt=(
                "Eres el Arquitecto de Software de AGENT LAB. "
                "Analiza los requisitos, inspecciona el workspace con list_files o query_code_graph, "
                "y publica en write_blackboard bajo 'arquitectura' una especificación clara de archivos, "
                "clases, firmas de funciones y casos borde para que el equipo implemente sin ambigüedades."
            ),
            allowed_tools=(
                "list_files",
                "read_file",
                "query_code_graph",
                "git_status",
                "read_blackboard",
                "write_blackboard",
            ),
            max_steps=12,
        )
    )

    agents.register(
        AgentConfig(
            id="explorador",
            name="Agente Explorador",
            role="Analista de Repositorio",
            description="Mapea archivos, dependencias AST y estado Git del workspace.",
            model_tier="fast",
            system_prompt=(
                "Eres el Agente Explorador de AGENT LAB. "
                "Usa list_files, read_file, query_code_graph y write_blackboard para mapear la estructura del workspace "
                "y compartir hallazgos técnicos concisos bajo la clave 'diagnostico'."
            ),
            allowed_tools=(
                "list_files",
                "read_file",
                "query_code_graph",
                "git_status",
                "git_diff",
                "read_blackboard",
                "write_blackboard",
            ),
            default_skills=("security_audit",),
            max_steps=12,
        )
    )

    agents.register(
        AgentConfig(
            id="programador",
            name="Agente Programador",
            role="Ingeniero de Software",
            description="Implementa código limpio, modular y tipado en el workspace.",
            model_tier="balanced",
            system_prompt=(
                "Eres un ingeniero de software experto en AGENT LAB. "
                "Consulta read_blackboard ('arquitectura' o 'diagnostico') y los archivos existentes antes de escribir. "
                "Implementa código limpio, bien estructurado y tipado usando write_file o edit_file."
            ),
            allowed_tools=(
                "list_files",
                "read_file",
                "write_file",
                "edit_file",
                "query_code_graph",
                "run_pytest",
                "read_blackboard",
                "write_blackboard",
            ),
            default_skills=("python_clean_code",),
            max_steps=18,
        )
    )

    agents.register(
        AgentConfig(
            id="tester",
            name="Agente QA & Testing",
            role="Ingeniero de Pruebas Automatizadas",
            description="Crea suites de pruebas unitarias y ejecuta pytest para verificar el código.",
            model_tier="balanced",
            system_prompt=(
                "Eres el Ingeniero de QA y Testing de AGENT LAB. "
                "Lee los módulos implementados en el workspace, escribe pruebas unitarias completas con pytest "
                "(cubriendo casos normales, límites y errores) y ejecútalas con run_pytest. "
                "Publica el resultado de las pruebas en write_blackboard bajo 'qa_report'."
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
            default_skills=("python_clean_code",),
            max_steps=16,
        )
    )

    agents.register(
        AgentConfig(
            id="refactorizador",
            name="Agente Refactorizador",
            role="Especialista en Código Limpio",
            description="Optimiza legibilidad, tipado, modularidad y corrige hallazgos de auditoría.",
            model_tier="balanced",
            system_prompt=(
                "Eres el Especialista en Refactorización y Código Limpio de AGENT LAB. "
                "Lee el código actual y las observaciones en read_blackboard ('revision' o 'qa_report'), "
                "mejora la estructura, elimina duplicación, añade type hints y verifica con run_pytest."
            ),
            allowed_tools=(
                "list_files",
                "read_file",
                "write_file",
                "edit_file",
                "query_code_graph",
                "run_pytest",
                "read_blackboard",
                "write_blackboard",
            ),
            default_skills=("python_clean_code",),
            max_steps=14,
        )
    )

    agents.register(
        AgentConfig(
            id="revisor",
            name="Agente Revisor",
            role="Auditor de Calidad y Seguridad",
            description="Audita seguridad, edge cases, calidad de código y ejecuta verificaciones.",
            model_tier="reasoning",
            system_prompt=(
                "Eres el Auditor Técnico y de Seguridad de AGENT LAB. "
                "Inspecciona el código generado en el workspace, revisa git_diff, detecta bugs, "
                "problemas de seguridad o casos borde, ejecuta run_pytest si hay tests, "
                "y publica tu veredicto técnico en write_blackboard bajo 'revision'."
            ),
            allowed_tools=(
                "list_files",
                "read_file",
                "query_code_graph",
                "git_status",
                "git_diff",
                "run_pytest",
                "read_blackboard",
                "write_blackboard",
            ),
            default_skills=("security_audit",),
            max_steps=12,
        )
    )

    agents.register(
        AgentConfig(
            id="documentador",
            name="Agente Documentador",
            role="Redactor Técnico y Guías",
            description="Genera documentación técnica, README.md, ejemplos de uso y reportes Markdown.",
            model_tier="fast",
            system_prompt=(
                "Eres el Documentador Técnico de AGENT LAB. "
                "Lee los archivos del workspace y el estado del Blackboard para redactar documentación clara, "
                "precisa y bien estructurada en Markdown (README.md, guías o informes técnicos)."
            ),
            allowed_tools=(
                "list_files",
                "read_file",
                "write_file",
                "edit_file",
                "query_code_graph",
                "read_blackboard",
                "write_blackboard",
            ),
            max_steps=10,
        )
    )

    agents.register(
        AgentConfig(
            id="analista",
            name="Agente Analista",
            role="Investigación y Especificación",
            description="Analiza requisitos complejos, evalúa alternativas y sintetiza planes accionables.",
            model_tier="reasoning",
            system_prompt=(
                "Eres el Analista de Requisitos y Estrategia de AGENT LAB. "
                "Descompone problemas complejos en criterios de aceptación claros, riesgos y recomendaciones, "
                "guardando tus conclusiones en write_blackboard bajo 'analisis'."
            ),
            allowed_tools=(
                "list_files",
                "read_file",
                "query_code_graph",
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