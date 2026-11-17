from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Devuelve la fecha y hora actual en UTC."""
    return datetime.now(timezone.utc)


class TokenLedgerEntry(BaseModel):
    """
    Registro contable inmutable (append-only) del consumo de una llamada LLM.
    """
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    run_id: UUID
    agent_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    step_number: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    latency_ms: int = Field(ge=0)
    used_knowledge_graph: bool = False
    timestamp: datetime = Field(default_factory=utc_now)