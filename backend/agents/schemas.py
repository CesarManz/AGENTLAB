from backend.tools.git_ops import GitCheckpoint
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Devuelve la fecha y hora actual en UTC."""
    return datetime.now(timezone.utc)


ModelTier = Literal["fast", "balanced", "reasoning"]

SessionStatus = Literal[
    "pending",
    "running",
    "awaiting_approval",
    "interrupted",
    "completed",
    "failed",
    "cancelled",
]

RunStatus = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "interrupted",
    "completed",
    "failed",
    "cancelled",
]


class AgentConfig(BaseModel):
    """
    Plantilla estática e inmutable de un tipo de agente de AGENT LAB.
    Nunca almacena el estado mutable de una sesión o ejecución.
    """
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, description="Slug único del agente")
    name: str = Field(min_length=1, description="Nombre visible del agente")
    role: str = Field(min_length=1, description="Función o especialidad del agente")
    description: str = Field(
        default="",
        description="Descripción breve de las responsabilidades del agente",
    )
    system_prompt: str = Field(
        min_length=1,
        description="Instrucciones base que definen el comportamiento del agente",
    )
    model_tier: ModelTier = Field(
        default="fast",
        description="Nivel de capacidad requerido por el agente",
    )
    provider_override: str | None = Field(
        default=None,
        description="Forzar un proveedor específico (ej. 'google')",
    )
    model_override: str | None = Field(
        default=None,
        description="Forzar un modelo específico (ej. 'gemini-2.5-flash')",
    )
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    allowed_tools: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Nombres de las herramientas que este agente puede invocar",
    )
    default_skills: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Skills cargadas por defecto para este agente",
    )
    max_steps: int = Field(default=10, ge=1, le=100)


class TaskSession(BaseModel):
    """
    Raíz de una solicitud del usuario, su workspace y presupuesto global.
    """
    id: UUID = Field(default_factory=uuid4)
    user_prompt: str = Field(min_length=1)
    status: SessionStatus = "pending"
    workspace_path: str = Field(min_length=1)
    blackboard: dict[str, Any] = Field(default_factory=dict)
    pipeline_stages: list[dict[str, str]] = Field(default_factory=list)
    current_stage_index: int = Field(default=0, ge=0)
    use_knowledge_graph: bool = False
    git_checkpoint: GitCheckpoint = Field(default_factory=GitCheckpoint)
    max_budget_tokens: int = Field(default=100_000, gt=0)
    total_tokens_used: int = Field(default=0, ge=0)
    final_output: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def remaining_budget_tokens(self) -> int:
        return max(0, self.max_budget_tokens - self.total_tokens_used)


class AgentRun(BaseModel):
    """
    Fuente de verdad del estado de ejecución de un agente concreto dentro de una sesión.
    """
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    parent_run_id: UUID | None = None
    dag_node_id: str | None = None
    agent_id: str = Field(min_length=1)
    task_instruction: str = Field(min_length=1)
    active_skills: list[str] = Field(default_factory=list)
    status: RunStatus = "queued"
    current_step: int = Field(default=0, ge=0)
    result_summary: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
