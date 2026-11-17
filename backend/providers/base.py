from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from backend.providers.schemas import LLMResponse, Message, ToolDefinition


class BaseProvider(ABC):
    """
    Contrato base agnóstico para todos los proveedores de IA en AGENT LAB.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identificador del proveedor (ej. 'google', 'anthropic', 'openai')."""
        ...

    @abstractmethod
    async def generate(
        self,
        messages: Sequence[Message],
        *,
        system_instruction: str | None = None,
        tools: Sequence[ToolDefinition] | None = None,
        temperature: float = 0.2,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """
        Ejecuta una inferencia a partir de mensajes estructurados y devuelve
        un LLMResponse normalizado.
        """
        ...

    async def close(self) -> None:
        """Libera recursos o clientes HTTP abiertos por el proveedor."""
        return None
