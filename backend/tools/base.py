import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from backend.providers.schemas import ToolDefinition
from backend.tools.schemas import RiskLevel, ToolResult


class BaseTool(ABC):
    """
    Contrato base stateless para todas las herramientas ejecutables por agentes.
    """

    name: str
    description: str
    args_schema: type[BaseModel]
    risk_level: RiskLevel = "safe"
    timeout_seconds: int = 30

    def to_definition(self) -> ToolDefinition:
        """
        Genera el DTO independiente que se envía al proveedor LLM.
        """
        return ToolDefinition(
            name=self.name,
            description=self.description,
            json_schema=self.args_schema.model_json_schema(),
        )

    @abstractmethod
    async def execute(
        self,
        tool_call_id: str,
        args: BaseModel,
        workspace_path: Path,
    ) -> ToolResult:
        """
        Ejecuta la lógica de la herramienta con argumentos ya validados.
        """
        ...

    async def validate_and_execute(
        self,
        tool_call_id: str,
        raw_arguments: dict[str, Any],
        workspace_path: Path,
    ) -> ToolResult:
        """
        Valida los argumentos crudos contra args_schema antes de invocar execute().
        Si la validación falla, devuelve un ToolResult con status='error'.
        """
        start = time.perf_counter()
        try:
            validated_args = self.args_schema(**raw_arguments)
        except ValidationError as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status="error",
                output=f"Argumentos inválidos para '{self.name}': {exc}",
                execution_time_ms=elapsed_ms,
            )

        return await self.execute(tool_call_id, validated_args, workspace_path)