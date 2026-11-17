import json
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from backend.storage.repository import StorageRepository
from backend.tools.base import BaseTool
from backend.tools.schemas import RiskLevel, ToolResult

CURRENT_SESSION_ID: ContextVar[UUID | None] = ContextVar("CURRENT_SESSION_ID", default=None)


class WriteBlackboardArgs(BaseModel):
    key: str = Field(
        min_length=1,
        description="Clave única bajo la cual guardar el hallazgo en la pizarra compartida (ej. 'plan', 'analisis_codigo').",
    )
    value: str = Field(
        min_length=1,
        description="Contenido o resumen estructurado a compartir con los demás agentes de la sesión.",
    )


class WriteBlackboardTool(BaseTool):
    name = "write_blackboard"
    description = "Publica información o resultados en la pizarra compartida (Blackboard) de la sesión para que otros agentes los lean."
    args_schema = WriteBlackboardArgs
    risk_level: RiskLevel = "safe"

    def __init__(self, repository: StorageRepository) -> None:
        self._repo = repository

    async def execute(
        self,
        tool_call_id: str,
        args: BaseModel,
        workspace_path: Path,
    ) -> ToolResult:
        assert isinstance(args, WriteBlackboardArgs)
        start = time.perf_counter()
        session_id = CURRENT_SESSION_ID.get()

        if session_id is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status="error",
                output="Error interno: no hay una TaskSession activa en el contexto.",
                execution_time_ms=0,
            )

        self._repo.update_blackboard(session_id, args.key, args.value)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status="success",
            output=f"Clave '{args.key}' guardada en el Blackboard compartido.",
            execution_time_ms=elapsed_ms,
        )


class ReadBlackboardArgs(BaseModel):
    key: str | None = Field(
        default=None,
        description="Clave específica a leer del Blackboard. Si se omite, devuelve todas las claves disponibles.",
    )


class ReadBlackboardTool(BaseTool):
    name = "read_blackboard"
    description = "Lee hallazgos publicados por otros agentes en la pizarra compartida (Blackboard) de la sesión."
    args_schema = ReadBlackboardArgs
    risk_level: RiskLevel = "safe"

    def __init__(self, repository: StorageRepository) -> None:
        self._repo = repository

    async def execute(
        self,
        tool_call_id: str,
        args: BaseModel,
        workspace_path: Path,
    ) -> ToolResult:
        assert isinstance(args, ReadBlackboardArgs)
        start = time.perf_counter()
        session_id = CURRENT_SESSION_ID.get()

        if session_id is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status="error",
                output="Error interno: no hay una TaskSession activa en el contexto.",
                execution_time_ms=0,
            )

        session = self._repo.get_session(session_id)
        board: dict[str, Any] = session.blackboard if session else {}

        if args.key:
            if args.key not in board:
                output = f"La clave '{args.key}' no existe aún en el Blackboard. Claves disponibles: {list(board.keys())}"
            else:
                output = json.dumps({args.key: board[args.key]}, ensure_ascii=False, indent=2)
        else:
            output = (
                json.dumps(board, ensure_ascii=False, indent=2)
                if board
                else "(El Blackboard de la sesión está vacío)"
            )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status="success",
            output=output,
            execution_time_ms=elapsed_ms,
        )
