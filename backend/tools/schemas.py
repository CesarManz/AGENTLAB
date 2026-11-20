from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Devuelve la fecha y hora actual en UTC."""
    return datetime.now(timezone.utc)


RiskLevel = Literal["safe", "moderate", "critical"]

ToolTerminalStatus = Literal["success", "error", "denied_by_user", "timeout"]

ToolExecutionStatus = Literal[
    "pending",
    "awaiting_approval",
    "approved",
    "running",
    "success",
    "error",
    "denied_by_user",
    "timeout",
]


class ToolResult(BaseModel):
    """
    Resultado inmediato e inmutable devuelto por BaseTool.execute().
    """
    model_config = ConfigDict(frozen=True)

    tool_call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    status: ToolTerminalStatus
    output: str
    execution_time_ms: int = Field(ge=0)
    artifacts_created: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Rutas relativas al workspace de archivos creados o modificados",
    )


class ToolExecution(BaseModel):
    """
    Registro persistente del ciclo de vida completo de una llamada a herramienta.
    Fuente de verdad para múltiples tool calls y flujo Human-in-the-Loop.
    """
    id: UUID = Field(default_factory=uuid4)
    tool_call_id: str = Field(min_length=1)
    run_id: UUID
    session_id: UUID
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel
    status: ToolExecutionStatus = "pending"
    output: str | None = None
    execution_time_ms: int | None = Field(default=None, ge=0)
    artifacts_created: list[str] = Field(default_factory=list)
    diff_preview: str | None = None
    target_file_sha256: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def apply_result(self, result: ToolResult) -> None:
        """
        Actualiza el estado de la ejecución con el resultado emitido por BaseTool.
        """
        if result.tool_call_id != self.tool_call_id:
            raise ValueError(
                f"El tool_call_id del resultado ({result.tool_call_id}) "
                f"no coincide con la ejecución ({self.tool_call_id})."
            )
        self.status = result.status
        self.output = result.output
        self.execution_time_ms = result.execution_time_ms
        self.artifacts_created = list(result.artifacts_created)
        self.updated_at = utc_now()