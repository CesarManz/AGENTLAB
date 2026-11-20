import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

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
    Coordina la ejecución secuencial y reanudable (tras HITL) de múltiples agentes
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
        self._session_locks: dict[UUID, asyncio.Lock] = {}

    async def run_pipeline(
        self,
        session: TaskSession,
        stages: list[PipelineStage],
    ) -> list[AgentRun]:
        if not stages:
            raise ValueError("El pipeline debe tener al menos una etapa.")

        workspace = Path(session.workspace_path).resolve()
        workspace.mkdir(parents=True, exist_ok=True)

        serialized_stages = [
            {
                "node_id": s.node_id,
                "agent_id": s.agent_id,
                "instruction": s.instruction,
            }
            for s in stages
        ]
        session.pipeline_stages = serialized_stages
        session.current_stage_index = 0
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

        return await self._execute_from_index(session=session, start_index=0)

    def _get_lock(self, session_id: UUID) -> asyncio.Lock:
        lock = self._session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_id] = lock
        return lock

    async def resume_interrupted_session(self, session_id: UUID) -> list[AgentRun]:
        """
        Reanuda de forma idempotente una sesión marcada como 'interrupted' tras un reinicio.
        - Si ya está 'completed', no re-ejecuta nada (idempotencia).
        - Si tiene aprobaciones HITL pendientes, lanza ValueError (409 en API).
        - Usa lock por sesión para evitar ejecuciones duplicadas concurrentes.
        """
        lock = self._get_lock(session_id)
        async with lock:
            session = self.repo.get_session(session_id)
            if session is None:
                raise KeyError(f"Sesión {session_id} no encontrada.")

            if session.status == "completed":
                return self.repo.list_runs_for_session(session_id)

            pending = self.repo.list_pending_approvals(session_id)
            if pending:
                raise ValueError(
                    "La sesión tiene aprobaciones HITL pendientes; resuélvelas antes de reanudar."
                )

            if session.status not in ("interrupted", "pending"):
                raise ValueError(
                    f"La sesión no se puede reanudar desde el estado actual '{session.status}'."
                )

            if session.pipeline_stages:
                return await self._execute_from_index(
                    session=session,
                    start_index=session.current_stage_index,
                )

            existing_runs = self.repo.list_runs_for_session(session_id)
            agent_id = existing_runs[-1].agent_id if existing_runs else "programador"
            run = await self.engine.execute_session(session, agent_id=agent_id)
            return [run]

    async def resume_pipeline_if_needed(self, session_id: UUID) -> list[AgentRun]:
        """
        Si la sesión pertenece a un pipeline y la etapa actual ya se completó tras resolver
        una aprobación HITL, continúa automáticamente con las etapas restantes.
        """
        session = self.repo.get_session(session_id)
        if session is None or not session.pipeline_stages:
            return []

        existing_runs = self.repo.list_runs_for_session(session_id)
        if not existing_runs:
            return []

        last_run = existing_runs[-1]
        if last_run.status != "completed":
            return []

        next_index = session.current_stage_index + 1
        if next_index >= len(session.pipeline_stages):
            return []

        return await self._execute_from_index(
            session=session,
            start_index=next_index,
            initial_parent_run_id=last_run.id,
        )

    async def _execute_from_index(
        self,
        *,
        session: TaskSession,
        start_index: int,
        initial_parent_run_id: UUID | None = None,
    ) -> list[AgentRun]:
        executed_runs: list[AgentRun] = []
        previous_run_id = initial_parent_run_id

        for idx in range(start_index, len(session.pipeline_stages)):
            stage_dict = session.pipeline_stages[idx]
            self.repo.update_session_pipeline(
                session.id,
                pipeline_stages=session.pipeline_stages,
                current_stage_index=idx,
            )

            instruction = (
                f"Objetivo global de la sesión: {session.user_prompt}\n\n"
                f"Tu misión específica en esta etapa ({stage_dict['node_id']}): {stage_dict['instruction']}\n"
                "Usa read_blackboard para revisar hallazgos previos si los hay, y write_blackboard para publicar tus resultados."
            )

            run = await self.engine.execute_agent_in_session(
                session=session,
                agent_id=stage_dict["agent_id"],
                task_instruction=instruction,
                parent_run_id=previous_run_id,
                dag_node_id=stage_dict["node_id"],
            )
            executed_runs.append(run)
            previous_run_id = run.id

            if run.status != "completed":
                # Pausa en HITL o fallo: el índice queda persistido en SQLite para reanudar luego.
                break

        return executed_runs
