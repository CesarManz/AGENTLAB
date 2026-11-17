from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from backend.agents.registry import AgentRegistry
from backend.agents.schemas import AgentConfig, AgentRun, TaskSession
from backend.core.config import ModelRoute, resolve_model_route
from backend.core.events import EventBus, SystemEvent
from backend.providers.base import BaseProvider
from backend.providers.schemas import Message
from backend.storage.repository import StorageRepository
from backend.storage.schemas import TokenLedgerEntry
from backend.tools.registry import ToolRegistry
from backend.tools.schemas import ToolExecution, ToolResult


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


ProviderFactory = Callable[[ModelRoute], BaseProvider]


class AgentEngine:
    """
    Motor unitario de ejecución de agentes (v0.2).
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

    async def execute_session(self, session: TaskSession, agent_id: str) -> AgentRun:
        """
        Ejecuta un flujo vertical completo de un agente sobre una TaskSession.
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

        route = resolve_model_route(
            config.model_tier,
            provider_override=config.provider_override,
            model_override=config.model_override,
        )
        provider = self.provider_factory(route)

        try:
            sequence = 0
            initial_msg = Message(
                run_id=run.id,
                session_id=session.id,
                sequence=sequence,
                role="user",
                content=run.task_instruction,
            )
            self.repo.append_message(initial_msg)
            sequence += 1

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

                assistant_msg = Message(
                    run_id=run.id,
                    session_id=session.id,
                    sequence=sequence,
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
                self.repo.append_message(assistant_msg)
                sequence += 1

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

                # Ejecutar cada ToolCall solicitada por el modelo
                for tc in response.tool_calls:
                    tool_result = await self._execute_single_tool_call(
                        session_id=session.id,
                        run_id=run.id,
                        config=config,
                        tool_call_id=tc.id,
                        tool_name=tc.tool_name,
                        arguments=tc.arguments,
                        workspace=workspace,
                    )

                    tool_msg = Message(
                        run_id=run.id,
                        session_id=session.id,
                        sequence=sequence,
                        role="tool",
                        content=tool_result.output,
                        tool_call_id=tc.id,
                        tool_name=tc.tool_name,
                    )
                    self.repo.append_message(tool_msg)
                    sequence += 1

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

    async def _execute_single_tool_call(
        self,
        *,
        session_id: UUID,
        run_id: UUID,
        config: AgentConfig,
        tool_call_id: str,
        tool_name: str,
        arguments: dict,
        workspace: Path,
    ) -> ToolResult:
        if tool_name not in config.allowed_tools:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                status="error",
                output=f"Permiso denegado: el agente '{config.id}' no tiene autorizada la herramienta '{tool_name}'.",
                execution_time_ms=0,
            )

        tool = self.tools.get(tool_name)
        execution = ToolExecution(
            tool_call_id=tool_call_id,
            run_id=run_id,
            session_id=session_id,
            tool_name=tool_name,
            arguments=arguments,
            risk_level=tool.risk_level,
            status="running",
        )
        self.repo.save_tool_execution(execution)

        result = await tool.validate_and_execute(tool_call_id, arguments, workspace)
        execution.apply_result(result)
        self.repo.save_tool_execution(execution)

        await self.events.publish(
            SystemEvent(
                event_type="TOOL_CALLED",
                session_id=session_id,
                run_id=run_id,
                payload={
                    "tool_name": tool_name,
                    "status": result.status,
                    "execution_time_ms": result.execution_time_ms,
                },
            )
        )
        return result

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