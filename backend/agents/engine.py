from backend.tools.git_ops import GitSafetyManager, build_hitl_file_preview, compute_file_sha256
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from backend.agents.registry import AgentRegistry
from backend.agents.schemas import AgentConfig, AgentRun, TaskSession
from backend.core.config import ModelRoute, resolve_model_route
from backend.core.pricing import estimate_call_cost_usd
from backend.core.skills import SkillRegistry
from backend.core.events import EventBus, SystemEvent
from backend.providers.base import BaseProvider
from backend.providers.schemas import Message, ToolCall
from backend.storage.repository import StorageRepository
from backend.storage.schemas import TokenLedgerEntry
from backend.tools.blackboard import CURRENT_SESSION_ID
from backend.tools.registry import ToolRegistry
from backend.tools.schemas import ToolExecution, ToolResult


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


ProviderFactory = Callable[[ModelRoute], BaseProvider]


class AgentEngine:
    """
    Motor unitario de ejecución de agentes con soporte Human-in-the-Loop y Blackboard (v0.4).
    """

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        repository: StorageRepository,
        event_bus: EventBus,
        provider_factory: ProviderFactory,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.agents = agent_registry
        self.tools = tool_registry
        self.repo = repository
        self.events = event_bus
        self.provider_factory = provider_factory
        self.skills = skill_registry or SkillRegistry()

    def _requires_approval(self, risk_level: str) -> bool:
        return risk_level != "safe"

    def _track_git_file_mutation(
        self,
        session: TaskSession,
        tool_name: str,
        arguments: dict[str, Any],
        existed_before: bool,
        result_status: str,
    ) -> None:
        if result_status != "success" or tool_name not in ("write_file", "edit_file"):
            return
        rel_path = str(arguments.get("path", "")).strip()
        if not rel_path:
            return
        fresh = self.repo.get_session(session.id) or session
        if not fresh.git_checkpoint.is_git_repo:
            return
        mgr = GitSafetyManager(fresh.workspace_path)
        updated_cp = mgr.record_agent_file_change(fresh.git_checkpoint, rel_path, existed_before)
        session.git_checkpoint = updated_cp
        self.repo.update_git_checkpoint(session.id, updated_cp)

    async def execute_session(self, session: TaskSession, agent_id: str) -> AgentRun:
        """
        Crea una nueva TaskSession en SQLite y ejecuta su AgentRun principal.
        """
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

        return await self.execute_agent_in_session(
            session=session,
            agent_id=agent_id,
            task_instruction=session.user_prompt,
        )

    async def execute_agent_in_session(
        self,
        *,
        session: TaskSession,
        agent_id: str,
        task_instruction: str,
        parent_run_id: UUID | None = None,
        dag_node_id: str | None = None,
    ) -> AgentRun:
        """
        Ejecuta un AgentRun concreto dentro de una TaskSession ya existente
        (usado tanto por execute_session como por MultiAgentOrchestrator).
        """
        config = self.agents.get(agent_id)
        workspace = Path(session.workspace_path).resolve()
        workspace.mkdir(parents=True, exist_ok=True)

        self.repo.update_session_status(session.id, status="running")

        run = AgentRun(
            session_id=session.id,
            parent_run_id=parent_run_id,
            dag_node_id=dag_node_id,
            agent_id=config.id,
            task_instruction=task_instruction,
            active_skills=[s.id for s in self.skills.resolve_for_task(task_instruction=task_instruction, default_skills=config.default_skills)],
            status="running",
            started_at=_utc_now(),
        )
        self.repo.create_run(run)
        await self.events.publish(
            SystemEvent(
                event_type="RUN_STARTED",
                session_id=session.id,
                run_id=run.id,
                payload={"agent_id": config.id, "dag_node_id": dag_node_id},
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

        token = CURRENT_SESSION_ID.set(session.id)
        try:
            return await self._run_loop(session=session, run=run, config=config, workspace=workspace)
        finally:
            CURRENT_SESSION_ID.reset(token)

    async def resolve_approval(self, execution_id: UUID, *, approved: bool) -> AgentRun:
        """
        Aprueba o rechaza una ToolExecution en estado 'awaiting_approval',
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

        token = CURRENT_SESSION_ID.set(session.id)
        try:
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
                target_rel = str(execution.arguments.get("path", "")).strip()
                existed_before = (workspace / target_rel).exists() if target_rel else False
                integrity_conflict = False
                if execution.target_file_sha256 and target_rel:
                    current_sha = compute_file_sha256(workspace / target_rel)
                    if current_sha != execution.target_file_sha256:
                        integrity_conflict = True
                if integrity_conflict:
                    result = ToolResult(
                        tool_call_id=execution.tool_call_id,
                        tool_name=execution.tool_name,
                        status="error",
                        output=(
                            f"Conflicto de integridad: el archivo '{target_rel}' cambió en disco "
                            "desde que se generó el diff de aprobación. Se canceló la escritura para no pisar cambios."
                        ),
                        execution_time_ms=0,
                    )
                else:
                    result = await tool.validate_and_execute(
                        execution.tool_call_id, execution.arguments, workspace
                    )
                execution.apply_result(result)
                self._track_git_file_mutation(session, execution.tool_name, execution.arguments, existed_before, result.status)
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

            run.status = "running"
            self.repo.update_run_state(run.id, status="running", current_step=run.current_step)
            self.repo.update_session_status(session.id, status="running")

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
        finally:
            CURRENT_SESSION_ID.reset(token)

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
                    system_instruction=config.system_prompt + self.skills.render_prompt_block([s for sid in run.active_skills if (s := self.skills.get(sid)) is not None]),
                    tools=tool_definitions if tool_definitions else None,
                    temperature=config.temperature,
                )

                call_cost = estimate_call_cost_usd(
                    provider=response.provider,
                    model_name=response.model_name,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cached_tokens=response.usage.cached_tokens,
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
                    estimated_cost_usd=call_cost,
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
            needs_approval = self._requires_approval(tool.risk_level)
            diff_preview, target_sha = (
                build_hitl_file_preview(workspace, tc.tool_name, tc.arguments)
                if needs_approval
                else (None, None)
            )
            execution = ToolExecution(
                tool_call_id=tc.id,
                run_id=run.id,
                session_id=session.id,
                tool_name=tc.tool_name,
                arguments=tc.arguments,
                risk_level=tool.risk_level,
                status="awaiting_approval" if needs_approval else "running",
                diff_preview=diff_preview,
                target_file_sha256=target_sha,
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
                            "diff_preview": execution.diff_preview,
                        },
                    )
                )
                return True

            target_rel = str(tc.arguments.get("path", "")).strip()
            existed_before = (workspace / target_rel).exists() if target_rel else False
            result = await tool.validate_and_execute(tc.id, tc.arguments, workspace)
            execution.apply_result(result)
            self._track_git_file_mutation(session, tc.tool_name, tc.arguments, existed_before, result.status)
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

