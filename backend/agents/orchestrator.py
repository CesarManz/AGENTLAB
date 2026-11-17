from dataclasses import dataclass
from pathlib import Path

from backend.agents.engine import AgentEngine
from backend.agents.schemas import AgentRun, TaskSession
from backend.core.events import EventBus, SystemEvent
from backend.storage.repository import StorageRepository


@dataclass(frozen=True)
class PipelineStage:
    node_id: str
    agent_id: str
    instruction: str


class MultiAgentOrchestrator:
    """
    Coordina la ejecución secuencial (pipeline) de múltiples agentes especializados
    compartiendo una TaskSession, su Blackboard y su presupuesto de tokens.
    """

    def __init__(
        self,
        *,
        engine: AgentEngine,
        repository: StorageRepository,
        event_bus: EventBus,
    ) -> None:
        self.engine = engine
        self.repo = repository
        self.events = event_bus

    async def run_pipeline(
        self,
        session: TaskSession,
        stages: list[PipelineStage],
    ) -> list[AgentRun]:
        if not stages:
            raise ValueError("El pipeline debe tener al menos una etapa.")

        workspace = Path(session.workspace_path).resolve()
        workspace.mkdir(parents=True, exist_ok=True)

        session.status = "running"
        self.repo.create_session(session)
        await self.events.publish(
            SystemEvent(
                event_type="SESSION_STARTED",
                session_id=session.id,
                payload={
                    "mode": "pipeline",
                    "stages": [s.agent_id for s in stages],
                    "workspace": str(workspace),
                },
            )
        )

        completed_runs: list[AgentRun] = []
        previous_run_id = None

        for stage in stages:
            instruction = (
                f"Objetivo global de la sesión: {session.user_prompt}\n\n"
                f"Tu misión específica en esta etapa ({stage.node_id}): {stage.instruction}\n"
                "Usa read_blackboard para revisar hallazgos previos si los hay, y write_blackboard para publicar tus resultados."
            )

            run = await self.engine.execute_agent_in_session(
                session=session,
                agent_id=stage.agent_id,
                task_instruction=instruction,
                parent_run_id=previous_run_id,
                dag_node_id=stage.node_id,
            )
            completed_runs.append(run)
            previous_run_id = run.id

            if run.status != "completed":
                # Si una etapa falla o queda esperando aprobación humana (HITL),
                # detenemos el avance automático del pipeline.
                break

        return completed_runs
