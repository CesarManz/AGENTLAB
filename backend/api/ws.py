from collections import defaultdict
from typing import Any
from uuid import UUID

from fastapi import WebSocket

from backend.core.events import SystemEvent


class SessionConnectionManager:
    """
    Puente entre EventBus y clientes WebSocket agrupados por session_id,
    con replay automático de eventos previos al conectar.
    """

    def __init__(self) -> None:
        self._connections: dict[UUID, set[WebSocket]] = defaultdict(set)
        self._history: dict[UUID, list[dict[str, Any]]] = defaultdict(list)

    async def connect(self, session_id: UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[session_id].add(websocket)

        await websocket.send_json(
            {
                "event_type": "WS_CONNECTED",
                "session_id": str(session_id),
            }
        )
        # Replay de eventos ocurridos antes de que el socket terminara de conectar
        for past_event in list(self._history.get(session_id, ())):
            await websocket.send_json(past_event)

    def disconnect(self, session_id: UUID, websocket: WebSocket) -> None:
        sockets = self._connections.get(session_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._connections.pop(session_id, None)

    async def broadcast_event(self, event: SystemEvent) -> None:
        message = event.model_dump(mode="json")
        self._history[event.session_id].append(message)

        sockets = list(self._connections.get(event.session_id, ()))
        if not sockets:
            return

        dead_sockets: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception:
                dead_sockets.append(ws)

        for ws in dead_sockets:
            self.disconnect(event.session_id, ws)
