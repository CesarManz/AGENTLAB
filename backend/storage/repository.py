import json
from datetime import datetime, timezone
from uuid import UUID

from backend.agents.schemas import AgentRun, RunStatus, SessionStatus, TaskSession
from backend.providers.schemas import Message, ToolCall
from backend.storage.database import Database
from backend.storage.schemas import TokenLedgerEntry
from backend.tools.schemas import ToolExecution


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StorageRepository:
    """
    Capa de persistencia SQLite para sesiones, ejecuciones, mensajes,
    herramientas y libro mayor de tokens (TokenLedger).
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    # -------------------------------------------------------------------------
    # TaskSession
    # -------------------------------------------------------------------------

    def create_session(self, session: TaskSession) -> TaskSession:
        sql = """
        INSERT INTO task_sessions (
            id, user_prompt, status, workspace_path, blackboard_json,
            use_knowledge_graph, max_budget_tokens, total_tokens_used,
            final_output, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.db.connect() as conn:
            conn.execute(
                sql,
                (
                    str(session.id),
                    session.user_prompt,
                    session.status,
                    session.workspace_path,
                    json.dumps(session.blackboard),
                    1 if session.use_knowledge_graph else 0,
                    session.max_budget_tokens,
                    session.total_tokens_used,
                    session.final_output,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
        return session

    def get_session(self, session_id: UUID) -> TaskSession | None:
        sql = "SELECT * FROM task_sessions WHERE id = ?"
        with self.db.connect() as conn:
            row = conn.execute(sql, (str(session_id),)).fetchone()

        if row is None:
            return None

        return TaskSession(
            id=UUID(row["id"]),
            user_prompt=row["user_prompt"],
            status=row["status"],
            workspace_path=row["workspace_path"],
            blackboard=json.loads(row["blackboard_json"]),
            use_knowledge_graph=bool(row["use_knowledge_graph"]),
            max_budget_tokens=row["max_budget_tokens"],
            total_tokens_used=row["total_tokens_used"],
            final_output=row["final_output"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def update_session_status(
        self,
        session_id: UUID,
        status: SessionStatus,
        final_output: str | None = None,
    ) -> None:
        sql = """
        UPDATE task_sessions
        SET status = ?, final_output = COALESCE(?, final_output), updated_at = ?
        WHERE id = ?
        """
        with self.db.connect() as conn:
            conn.execute(
                sql,
                (status, final_output, _utc_iso(), str(session_id)),
            )

    def has_available_budget(self, session_id: UUID) -> bool:
        sql = """
        SELECT total_tokens_used, max_budget_tokens
        FROM task_sessions
        WHERE id = ?
        """
        with self.db.connect() as conn:
            row = conn.execute(sql, (str(session_id),)).fetchone()

        if row is None:
            raise KeyError(f"No se encontró la sesión {session_id}")

        return int(row["total_tokens_used"]) < int(row["max_budget_tokens"])

    # -------------------------------------------------------------------------
    # AgentRun
    # -------------------------------------------------------------------------

    def create_run(self, run: AgentRun) -> AgentRun:
        sql = """
        INSERT INTO agent_runs (
            id, session_id, parent_run_id, dag_node_id, agent_id,
            task_instruction, active_skills_json, status, current_step,
            result_summary, error_message, started_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.db.connect() as conn:
            conn.execute(
                sql,
                (
                    str(run.id),
                    str(run.session_id),
                    str(run.parent_run_id) if run.parent_run_id else None,
                    run.dag_node_id,
                    run.agent_id,
                    run.task_instruction,
                    json.dumps(run.active_skills),
                    run.status,
                    run.current_step,
                    run.result_summary,
                    run.error_message,
                    run.started_at.isoformat() if run.started_at else None,
                    run.completed_at.isoformat() if run.completed_at else None,
                ),
            )
        return run

    def update_run_state(
        self,
        run_id: UUID,
        *,
        status: RunStatus,
        current_step: int,
        result_summary: str | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        sql = """
        UPDATE agent_runs
        SET status = ?,
            current_step = ?,
            result_summary = COALESCE(?, result_summary),
            error_message = COALESCE(?, error_message),
            started_at = COALESCE(?, started_at),
            completed_at = COALESCE(?, completed_at)
        WHERE id = ?
        """
        with self.db.connect() as conn:
            conn.execute(
                sql,
                (
                    status,
                    current_step,
                    result_summary,
                    error_message,
                    started_at.isoformat() if started_at else None,
                    completed_at.isoformat() if completed_at else None,
                    str(run_id),
                ),
            )

    # -------------------------------------------------------------------------
    # Messages
    # -------------------------------------------------------------------------

    def append_message(self, message: Message) -> Message:
        sql = """
        INSERT INTO messages (
            id, run_id, session_id, sequence, role, content,
            tool_calls_json, tool_call_id, tool_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        serialized_calls = [tc.model_dump() for tc in message.tool_calls]
        with self.db.connect() as conn:
            conn.execute(
                sql,
                (
                    str(message.id),
                    str(message.run_id),
                    str(message.session_id),
                    message.sequence,
                    message.role,
                    message.content,
                    json.dumps(serialized_calls),
                    message.tool_call_id,
                    message.tool_name,
                    message.created_at.isoformat(),
                ),
            )
        return message

    def list_messages(self, run_id: UUID) -> list[Message]:
        sql = """
        SELECT * FROM messages
        WHERE run_id = ?
        ORDER BY sequence ASC
        """
        with self.db.connect() as conn:
            rows = conn.execute(sql, (str(run_id),)).fetchall()

        messages: list[Message] = []
        for row in rows:
            raw_calls = json.loads(row["tool_calls_json"])
            tool_calls = tuple(ToolCall(**tc) for tc in raw_calls)
            messages.append(
                Message(
                    id=UUID(row["id"]),
                    run_id=UUID(row["run_id"]),
                    session_id=UUID(row["session_id"]),
                    sequence=row["sequence"],
                    role=row["role"],
                    content=row["content"],
                    tool_calls=tool_calls,
                    tool_call_id=row["tool_call_id"],
                    tool_name=row["tool_name"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return messages

    # -------------------------------------------------------------------------
    # ToolExecutions
    # -------------------------------------------------------------------------

    def save_tool_execution(self, execution: ToolExecution) -> ToolExecution:
        sql = """
        INSERT INTO tool_executions (
            id, tool_call_id, run_id, session_id, tool_name,
            arguments_json, risk_level, status, output,
            execution_time_ms, artifacts_created_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status = excluded.status,
            output = excluded.output,
            execution_time_ms = excluded.execution_time_ms,
            artifacts_created_json = excluded.artifacts_created_json,
            updated_at = excluded.updated_at
        """
        with self.db.connect() as conn:
            conn.execute(
                sql,
                (
                    str(execution.id),
                    execution.tool_call_id,
                    str(execution.run_id),
                    str(execution.session_id),
                    execution.tool_name,
                    json.dumps(execution.arguments),
                    execution.risk_level,
                    execution.status,
                    execution.output,
                    execution.execution_time_ms,
                    json.dumps(execution.artifacts_created),
                    execution.created_at.isoformat(),
                    execution.updated_at.isoformat(),
                ),
            )
        return execution

    # -------------------------------------------------------------------------
    # TokenLedger (Append-only + incremento atómico en TaskSession)
    # -------------------------------------------------------------------------

    def record_token_usage(self, entry: TokenLedgerEntry) -> TokenLedgerEntry:
        insert_sql = """
        INSERT INTO token_ledger (
            id, session_id, run_id, agent_id, provider, model_name,
            step_number, input_tokens, output_tokens, cached_tokens,
            total_tokens, estimated_cost_usd, latency_ms,
            used_knowledge_graph, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        update_session_sql = """
        UPDATE task_sessions
        SET total_tokens_used = total_tokens_used + ?, updated_at = ?
        WHERE id = ?
        """
        tokens_to_add = entry.total_tokens or 0

        with self.db.connect() as conn:
            conn.execute(
                insert_sql,
                (
                    str(entry.id),
                    str(entry.session_id),
                    str(entry.run_id),
                    entry.agent_id,
                    entry.provider,
                    entry.model_name,
                    entry.step_number,
                    entry.input_tokens,
                    entry.output_tokens,
                    entry.cached_tokens,
                    entry.total_tokens,
                    entry.estimated_cost_usd,
                    entry.latency_ms,
                    1 if entry.used_knowledge_graph else 0,
                    entry.timestamp.isoformat(),
                ),
            )
            conn.execute(
                update_session_sql,
                (tokens_to_add, _utc_iso(), str(entry.session_id)),
            )

        return entry