import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Devuelve la fecha y hora actual en UTC."""
    return datetime.now(timezone.utc)


EventType = Literal[
    "SESSION_STARTED",
    "SESSION_COMPLETED",
    "SESSION_FAILED",
    "RUN_STARTED",
    "STEP_COMPLETED",
    "TOOL_CALLED",
    "APPROVAL_REQUIRED",
    "APPROVAL_RESOLVED",
    "FILE_MODIFIED",
    "TOKEN_RECORDED",
    "RUN_COMPLETED",
    "RUN_FAILED",
]


class SystemEvent(BaseModel):
    """
    Evento inmutable emitido por cualquier componente interno de AGENT LAB.
    """
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    session_id: UUID
    run_id: UUID | None = None
    timestamp: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)


EventHandler = Callable[[SystemEvent], Awaitable[None] | None]


class EventBus:
    """
    Bus de eventos asíncrono en proceso (Pub/Sub) con aislamiento de errores.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: EventType | Literal["*"], handler: EventHandler) -> None:
        """
        Registra un listener para un tipo de evento específico o '*' para todos.
        """
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType | Literal["*"], handler: EventHandler) -> None:
        """
        Elimina un listener previamente registrado.
        """
        if handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler)

    async def publish(self, event: SystemEvent) -> None:
        """
        Notifica a todos los suscriptores del evento y a los suscriptores globales ('*').
        Si un listener falla, se registra el error sin afectar al resto ni al emisor.
        """
        handlers = list(self._subscribers[event.event_type]) + list(self._subscribers["*"])

        for handler in handlers:
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception(
                    "Error en listener al procesar evento '%s' (id=%s)",
                    event.event_type,
                    event.id,
                )