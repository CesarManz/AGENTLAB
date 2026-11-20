import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("data/agent_lab.db")


class Database:
    """
    Gestor de conexión y esquema SQLite configurado en modo WAL
    para operaciones concurrentes seguras.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        """
        Abre una conexión SQLite con WAL, foreign_keys y row_factory por nombre.
        """
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def initialize(self) -> None:
        """
        Crea las tablas e índices principales de AGENT LAB v0.2 si no existen.
        """
        schema_sql = """
        CREATE TABLE IF NOT EXISTS task_sessions (
            id TEXT PRIMARY KEY,
            user_prompt TEXT NOT NULL,
            status TEXT NOT NULL,
            workspace_path TEXT NOT NULL,
            blackboard_json TEXT NOT NULL DEFAULT '{}',
            pipeline_stages_json TEXT NOT NULL DEFAULT '[]',
            current_stage_index INTEGER NOT NULL DEFAULT 0,
            use_knowledge_graph INTEGER NOT NULL DEFAULT 0,
            git_checkpoint_json TEXT NOT NULL DEFAULT '{}',
            max_budget_tokens INTEGER NOT NULL,
            total_tokens_used INTEGER NOT NULL DEFAULT 0,
            final_output TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_runs (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            parent_run_id TEXT,
            dag_node_id TEXT,
            agent_id TEXT NOT NULL,
            task_instruction TEXT NOT NULL,
            active_skills_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL,
            current_step INTEGER NOT NULL DEFAULT 0,
            result_summary TEXT,
            error_message TEXT,
            started_at TEXT,
            completed_at TEXT,
            FOREIGN KEY (session_id) REFERENCES task_sessions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_agent_runs_session
            ON agent_runs(session_id);

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_calls_json TEXT NOT NULL DEFAULT '[]',
            tool_call_id TEXT,
            tool_name TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (run_id, sequence),
            FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (session_id) REFERENCES task_sessions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_messages_run_seq
            ON messages(run_id, sequence);

        CREATE TABLE IF NOT EXISTS tool_executions (
            id TEXT PRIMARY KEY,
            tool_call_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            arguments_json TEXT NOT NULL DEFAULT '{}',
            risk_level TEXT NOT NULL,
            status TEXT NOT NULL,
            output TEXT,
            execution_time_ms INTEGER,
            artifacts_created_json TEXT NOT NULL DEFAULT '[]',
            diff_preview TEXT,
            target_file_sha256 TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (session_id) REFERENCES task_sessions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_tool_executions_run
            ON tool_executions(run_id);

        CREATE TABLE IF NOT EXISTS token_ledger (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            model_name TEXT NOT NULL,
            step_number INTEGER NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cached_tokens INTEGER,
            total_tokens INTEGER,
            estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
            latency_ms INTEGER NOT NULL,
            used_knowledge_graph INTEGER NOT NULL DEFAULT 0,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES task_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_token_ledger_session
            ON token_ledger(session_id);
        CREATE INDEX IF NOT EXISTS idx_token_ledger_run
            ON token_ledger(run_id);
        CREATE INDEX IF NOT EXISTS idx_token_ledger_agent
            ON token_ledger(agent_id);
        """

        with self.connect() as conn:
            conn.executescript(schema_sql)
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(task_sessions)").fetchall()}
            if "pipeline_stages_json" not in cols:
                conn.execute("ALTER TABLE task_sessions ADD COLUMN pipeline_stages_json TEXT NOT NULL DEFAULT '[]'")
            if "current_stage_index" not in cols:
                conn.execute("ALTER TABLE task_sessions ADD COLUMN current_stage_index INTEGER NOT NULL DEFAULT 0")
            if "git_checkpoint_json" not in cols:
                conn.execute("ALTER TABLE task_sessions ADD COLUMN git_checkpoint_json TEXT NOT NULL DEFAULT '{}'")
            te_cols = {row["name"] for row in conn.execute("PRAGMA table_info(tool_executions)").fetchall()}
            if "diff_preview" not in te_cols:
                conn.execute("ALTER TABLE tool_executions ADD COLUMN diff_preview TEXT")
            if "target_file_sha256" not in te_cols:
                conn.execute("ALTER TABLE tool_executions ADD COLUMN target_file_sha256 TEXT")