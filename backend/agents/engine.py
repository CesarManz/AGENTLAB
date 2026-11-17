from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from backend.agents.registry import AgentRegistry
from backend.agents.schemas import AgentConfig, AgentRun, TaskSession
from backend.core.config import ModelRoute, resolve_model_route
from backend.core.events import EventBus, SystemEvent
from backend.providers.base import BaseProvider
from backend.providers.schemas import Message, ToolCall
from backend.storage.repository import StorageRepository
from backend.storage.schemas import TokenLedgerEntry
from backend.tools.registry import ToolRegistry
from backend.tools.schemas import ToolExecution, ToolResult


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


ProviderFactory = Callable[[ModelRoute], BaseProvider]


class AgentEngine:
    """
    Motor unitario de ejecución de agentes con soporte Human-in-the-Loop (v0.3).
    Agnóstico a proveedores concretos, FastAPI y frameworks externos.
    """

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        repository: StorageRepository,
        event_bus: EventBus,
        provider_factory: ProviderFactory,
    ) -> None:
        self.agents = agent_registry
        self.tools = tool_registry
        self.repo = repository
        self.events = event_bus
        self.provider_factory = provider_factory

    def _requires_approval(self, risk_level: str) -> bool:
        return risk_level != "safe"

    async def execute_session(self, session: TaskSession, agent_id: str) -> AgentRun:
        """
        Inicia una nueva TaskSession desde cero con el agente indicado.
        """
        config = self.agents.get(agent_id)
        workspace = Path(session.workspace_path).resolve()
        workspace.mkdir(parents=True, exist_ok=True)

        session.status = "running"
        self.repo.create_session(session)
        await self.events.publish(
            SystemEvent(
                event_type="SESSION_STARTED",
                session_id=session.id,
                payload={"agent_id": agent_id, "workspace": str(workspace)},
            )
        )

        run = AgentRun(
            session_id=session.id,
            agent_id=config.id,
            task_instruction=session.user_prompt,
            active_skills=list(config.default_skills),
            status="running",
            started_at=_utc_now(),
        )
        self.repo.create_run(run)
        await self.events.publish(
            SystemEvent(
                event_type="RUN_STARTED",
                session_id=session.id,
                run_id=run.id,
                payload={"agent_id": config.id},
            )
        )

        initial_msg = Message(
            run_id=run.id,
            session_id=session.id,
            sequence=0,
            role="user",
            content=run.task_instruction,
        )
        self.repo.append_message(initial_msg)

        return await self._run_loop(session=session, run=run, config=config, workspace=workspace)

    async def resolve_approval(self, execution_id: UUID, *, approved: bool) -> AgentRun:
        """
        Aprueba o rechaza una ToolExecution en estado 'pending_approval',
        procesa las llamadas restantes del turno y reanuda el AgentRun.
        """
        execution = self.repo.get_tool_execution(execution_id)
        if execution is None:
            raise KeyError(f"No se encontró la ejecución de herramienta {execution_id}")
        if execution.status != "awaiting_approval":
            raise ValueError(
                f"La ejecución {execution_id} no espera aprobación (estado actual: {execution.status})."
            )

        run = self.repo.get_run(execution.run_id)
        if run is None:
            raise KeyError(f"No se encontró el AgentRun {execution.run_id}")

        session = self.repo.get_session(execution.session_id)
        if session is None:
            raise KeyError(f"No se encontró la sesión {execution.session_id}")

        config = self.agents.get(run.agent_id)
        workspace = Path(session.workspace_path).resolve()

        await self.events.publish(
            SystemEvent(
                event_type="APPROVAL_RESOLVED",
                session_id=session.id,
                run_id=run.id,
                payload={
                    "execution_id": str(execution.id),
                    "tool_name": execution.tool_name,
                    "approved": approved,
                },
            )
        )

        if approved:
            execution.status = "running"
            self.repo.save_tool_execution(execution)

            tool = self.tools.get(execution.tool_name)
            result = await tool.validate_and_execute(
                execution.tool_call_id, execution.arguments, workspace
            )
            execution.apply_result(result)
            self.repo.save_tool_execution(execution)

            await self.events.publish(
                SystemEvent(
                    event_type="TOOL_CALLED",
                    session_id=session.id,
                    run_id=run.id,
                    payload={
                        "tool_name": execution.tool_name,
                        "status": result.status,
                        "execution_time_ms": result.execution_time_ms,
                    },
                )
            )
            tool_output = result.output
        else:
            execution.status = "denied_by_user"
            execution.output = "Acción rechazada por el usuario."
            execution.updated_at = _utc_now()
            self.repo.save_tool_execution(execution)
            tool_output = (
                f"Permiso denegado por el usuario: la ejecución de '{execution.tool_name}' "
                "fue rechazada manualmente. No vuelvas a intentarla con los mismos parámetros."
            )

        next_seq = self.repo.get_next_sequence(run.id)
        self.repo.append_message(
            Message(
                run_id=run.id,
                session_id=session.id,
                sequence=next_seq,
                role="tool",
                content=tool_output,
                tool_call_id=execution.tool_call_id,
                tool_name=execution.tool_name,
            )
        )

        # Reactivar estado del run y sesión
        run.status = "running"
        self.repo.update_run_state(run.id, status="running", current_step=run.current_step)
        self.repo.update_session_status(session.id, status="running")

        # Verificar si quedaron más tool_calls sin responder en el último turno del asistente
        history = self.repo.list_messages(run.id)
        pending_calls = self._find_unanswered_tool_calls(history)
        if pending_calls:
            paused = await self._process_tool_calls(
                session=session,
                run=run,
                config=config,
                tool_calls=pending_calls,
                workspace=workspace,
            )
            if paused:
                return run

        self.repo.update_run_state(run.id, status="running", current_step=run.current_step)
        await self.events.publish(
            SystemEvent(
                event_type="STEP_COMPLETED",
                session_id=session.id,
                run_id=run.id,
                payload={"step": run.current_step},
            )
        )

        return await self._run_loop(session=session, run=run, config=config, workspace=workspace)

    def _find_unanswered_tool_calls(self, history: list[Message]) -> list[ToolCall]:
        last_assistant_idx = -1
        for idx, msg in enumerate(history):
            if msg.role == "assistant":
                last_assistant_idx = idx

        if last_assistant_idx == -1:
            return []

        assistant_msg = history[last_assistant_idx]
        if not assistant_msg.tool_calls:
            return []

        answered_ids = {
            msg.tool_call_id
            for msg in history[last_assistant_idx + 1 :]
            if msg.role == "tool" and msg.tool_call_id
        }
        return [tc for tc in assistant_msg.tool_calls if tc.id not in answered_ids]

    async def _run_loop(
        self,
        *,
        session: TaskSession,
        run: AgentRun,
        config: AgentConfig,
        workspace: Path,
    ) -> AgentRun:
        route = resolve_model_route(
            config.model_tier,
            provider_override=config.provider_override,
            model_override=config.model_override,
        )
        provider = self.provider_factory(route)

        try:
            tool_definitions = self.tools.get_definitions_for(config.allowed_tools)

            while run.current_step < config.max_steps:
                if not self.repo.has_available_budget(session.id):
                    return await self._fail_run(
                        session.id,
                        run,
                        "Presupuesto máximo de tokens de la sesión agotado.",
                    )

                run.current_step += 1
                history = self.repo.list_messages(run.id)

                response = await provider.generate(
                    history,
                    system_instruction=config.system_prompt,
                    tools=tool_definitions if tool_definitions else None,
                    temperature=config.temperature,
                )

                ledger_entry = TokenLedgerEntry(
                    session_id=session.id,
                    run_id=run.id,
                    agent_id=config.id,
                    provider=response.provider,
                    model_name=response.model_name,
                    step_number=run.current_step,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cached_tokens=response.usage.cached_tokens,
                    total_tokens=response.usage.total_tokens,
                    latency_ms=response.latency_ms,
                    used_knowledge_graph=session.use_knowledge_graph,
                )
                self.repo.record_token_usage(ledger_entry)
                await self.events.publish(
                    SystemEvent(
                        event_type="TOKEN_RECORDED",
                        session_id=session.id,
                        run_id=run.id,
                        payload={
                            "step": run.current_step,
                            "total_tokens": ledger_entry.total_tokens,
                            "latency_ms": ledger_entry.latency_ms,
                        },
                    )
                )

                next_seq = self.repo.get_next_sequence(run.id)
                assistant_msg = Message(
                    run_id=run.id,
                    session_id=session.id,
                    sequence=next_seq,
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
                self.repo.append_message(assistant_msg)

                if response.finish_reason == "error":
                    return await self._fail_run(
                        session.id,
                        run,
                        response.content or "Error desconocido en proveedor LLM.",
                    )

                if not response.tool_calls:
                    final_text = response.content or ""
                    run.status = "completed"
                    run.result_summary = final_text
                    run.completed_at = _utc_now()

                    self.repo.update_run_state(
                        run.id,
                        status="completed",
                        current_step=run.current_step,
                        result_summary=final_text,
                        completed_at=run.completed_at,
                    )
                    self.repo.update_session_status(
                        session.id,
                        status="completed",
                        final_output=final_text,
                    )
                    await self.events.publish(
                        SystemEvent(
                            event_type="STEP_COMPLETED",
                            session_id=session.id,
                            run_id=run.id,
                            payload={"step": run.current_step},
                        )
                    )
                    await self.events.publish(
                        SystemEvent(
                            event_type="RUN_COMPLETED",
                            session_id=session.id,
                            run_id=run.id,
                            payload={"steps": run.current_step},
                        )
                    )
                    return run

                paused = await self._process_tool_calls(
                    session=session,
                    run=run,
                    config=config,
                    tool_calls=list(response.tool_calls),
                    workspace=workspace,
                )
                if paused:
                    return run

                self.repo.update_run_state(
                    run.id,
                    status="running",
                    current_step=run.current_step,
                )
                await self.events.publish(
                    SystemEvent(
                        event_type="STEP_COMPLETED",
                        session_id=session.id,
                        run_id=run.id,
                        payload={"step": run.current_step},
                    )
                )

            return await self._fail_run(
                session.id,
                run,
                f"Se alcanzó el límite máximo de {config.max_steps} pasos sin finalizar.",
            )

        except Exception as exc:
            return await self._fail_run(
                session.id,
                run,
                f"Excepción inesperada en AgentEngine: {exc}",
            )
        finally:
            await provider.close()

    async def _process_tool_calls(
        self,
        *,
        session: TaskSession,
        run: AgentRun,
        config: AgentConfig,
        tool_calls: list[ToolCall],
        workspace: Path,
    ) -> bool:
        """
        Ejecuta una secuencia de ToolCalls. Devuelve True si se pausó esperando
        aprobación humana (HITL), o False si todas se completaron.
        """
        for tc in tool_calls:
            if tc.tool_name not in config.allowed_tools:
                result = ToolResult(
                    tool_call_id=tc.id,
                    tool_name=tc.tool_name,
                    status="error",
                    output=f"Permiso denegado: el agente '{config.id}' no tiene autorizada la herramienta '{tc.tool_name}'.",
                    execution_time_ms=0,
                )
                next_seq = self.repo.get_next_sequence(run.id)
                self.repo.append_message(
                    Message(
                        run_id=run.id,
                        session_id=session.id,
                        sequence=next_seq,
                        role="tool",
                        content=result.output,
                        tool_call_id=tc.id,
                        tool_name=tc.tool_name,
                    )
                )
                continue

            tool = self.tools.get(tc.tool_name)
            execution = ToolExecution(
                tool_call_id=tc.id,
                run_id=run.id,
                session_id=session.id,
                tool_name=tc.tool_name,
                arguments=tc.arguments,
                risk_level=tool.risk_level,
                status="awaiting_approval" if self._requires_approval(tool.risk_level) else "running",
            )
            self.repo.save_tool_execution(execution)

            if execution.status == "awaiting_approval":
                run.status = "awaiting_approval"
                self.repo.update_run_state(
                    run.id,
                    status="awaiting_approval",
                    current_step=run.current_step,
                )
                self.repo.update_session_status(session.id, status="awaiting_approval")
                await self.events.publish(
                    SystemEvent(
                        event_type="APPROVAL_REQUIRED",
                        session_id=session.id,
                        run_id=run.id,
                        payload={
                            "execution_id": str(execution.id),
                            "tool_name": execution.tool_name,
                            "risk_level": execution.risk_level,
                            "arguments": execution.arguments,
                        },
                    )
                )
                return True

            result = await tool.validate_and_execute(tc.id, tc.arguments, workspace)
            execution.apply_result(result)
            self.repo.save_tool_execution(execution)

            await self.events.publish(
                SystemEvent(
                    event_type="TOOL_CALLED",
                    session_id=session.id,
                    run_id=run.id,
                    payload={
                        "tool_name": tc.tool_name,
                        "status": result.status,
                        "execution_time_ms": result.execution_time_ms,
                    },
                )
            )

            next_seq = self.repo.get_next_sequence(run.id)
            self.repo.append_message(
                Message(
                    run_id=run.id,
                    session_id=session.id,
                    sequence=next_seq,
                    role="tool",
                    content=result.output,
                    tool_call_id=tc.id,
                    tool_name=tc.tool_name,
                )
            )

        return False

    async def _fail_run(
        self, session_id: UUID, run: AgentRun, error_message: str
    ) -> AgentRun:
        run.status = "failed"
        run.error_message = error_message
        run.completed_at = _utc_now()

        self.repo.update_run_state(
            run.id,
            status="failed",
            current_step=run.current_step,
            error_message=error_message,
            completed_at=run.completed_at,
        )
        self.repo.update_session_status(session_id, status="failed")
        await self.events.publish(
            SystemEvent(
                event_type="RUN_FAILED",
                session_id=session_id,
                run_id=run.id,
                payload={"error": error_message},
            )
        )
        return run

