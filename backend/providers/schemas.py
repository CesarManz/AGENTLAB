from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    """Devuelve la fecha y hora actual en UTC."""
    return datetime.now(timezone.utc)


class ToolDefinition(BaseModel):
    """
    DTO independiente que describe una herramienta ante cualquier proveedor LLM.
    Evita que BaseProvider tenga que importar BaseTool.
    """
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, description="Nombre único de la herramienta")
    description: str = Field(min_length=1, description="Cuándo y cómo usar la herramienta")
    json_schema: dict[str, Any] = Field(
        description="Esquema JSON de los argumentos esperados"
    )


class ToolCall(BaseModel):
    """
    Solicitud emitida por el modelo para ejecutar una herramienta concreta.
    """
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, description="ID de correlación de la llamada")
    tool_name: str = Field(min_length=1, description="Nombre de la herramienta invocada")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Argumentos enviados por el modelo"
    )
    provider_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadatos opacos del proveedor necesarios para turnos siguientes (ej. thought_signature)"
    )


class TokenUsage(BaseModel):
    """
    Métricas de consumo de tokens normalizadas.
    Usa None cuando el proveedor no informa un valor específico.
    """
    model_config = ConfigDict(frozen=True)

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def compute_total_if_missing(self) -> "TokenUsage":
        if (
            self.total_tokens is None
            and self.input_tokens is not None
            and self.output_tokens is not None
        ):
            object.__setattr__(
                self, "total_tokens", self.input_tokens + self.output_tokens
            )
        return self


class LLMResponse(BaseModel):
    """
    Respuesta normalizada de cualquier proveedor de IA hacia el Agent Engine.
    """
    model_config = ConfigDict(frozen=True)

    content: str | None = None
    parsed_output: dict[str, Any] | None = None
    tool_calls: tuple[ToolCall, ...] = Field(default_factory=tuple)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    finish_reason: Literal["stop", "tool_calls", "max_tokens", "safety", "error"]
    latency_ms: int = Field(ge=0)


class Message(BaseModel):
    """
    Unidad atómica e inmutable del historial de conversación de un AgentRun.
    """
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    session_id: UUID
    sequence: int = Field(ge=0, description="Orden secuencial dentro del AgentRun")
    role: Literal["user", "assistant", "tool"]
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = Field(default_factory=tuple)
    tool_call_id: str | None = None
    tool_name: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_role_constraints(self) -> "Message":
        if self.role == "tool":
            if not self.tool_call_id or not self.tool_name:
                raise ValueError(
                    "Un mensaje con role='tool' debe incluir 'tool_call_id' y 'tool_name'."
                )
            if self.content is None:
                raise ValueError(
                    "Un mensaje con role='tool' debe incluir 'content' con el resultado."
                )

        if self.role != "assistant" and len(self.tool_calls) > 0:
            raise ValueError(
                "Solo los mensajes con role='assistant' pueden contener 'tool_calls'."
            )

        if self.role != "tool" and (self.tool_call_id is not None or self.tool_name is not None):
            raise ValueError(
                "'tool_call_id' y 'tool_name' son exclusivos de mensajes con role='tool'."
            )

        return self
