from collections.abc import Sequence

from backend.providers.schemas import ToolDefinition
from backend.tools.base import BaseTool


class ToolRegistry:
    """
    Registro central de herramientas disponibles y filtro de permisos por agente.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> BaseTool:
        if tool.name in self._tools:
            raise ValueError(f"Ya existe una herramienta registrada con nombre: {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, tool_name: str) -> BaseTool:
        tool = self._tools.get(tool_name)
        if tool is None:
            raise KeyError(f"Herramienta no encontrada: {tool_name}")
        return tool

    def has(self, tool_name: str) -> bool:
        return tool_name in self._tools

    def get_definitions_for(self, allowed_tools: Sequence[str]) -> list[ToolDefinition]:
        """
        Devuelve únicamente las definiciones DTO de las herramientas permitidas
        para un agente específico.
        """
        definitions: list[ToolDefinition] = []
        for name in allowed_tools:
            tool = self.get(name)
            definitions.append(tool.to_definition())
        return definitions

    def list_all(self) -> list[BaseTool]:
        return list(self._tools.values())