"""WebSocket connection manager for L.I.R.A.

Manages real-time push notifications to connected dashboard clients.
When data mutations occur (transactions, investments, etc.), all connected
WebSocket clients receive a `data_changed` event so they can refresh.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.debug("WebSocket connected — total: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a closed WebSocket connection."""
        with suppress(ValueError):
            self.active_connections.remove(websocket)
        logger.debug("WebSocket disconnected — total: %d", len(self.active_connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a JSON message to all connected clients."""
        if not self.active_connections:
            return
        text = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in list(self.active_connections):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def notify_data_changed(self, event: str = "data_changed") -> None:
        """Fire-and-forget broadcast callable from synchronous code.

        Schedules the broadcast on the running event loop. Safe to call
        from MCP tools or any non-async context running inside the same
        process as the FastAPI server.
        """
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(
            self.broadcast({"type": event}), loop
        )


# Singleton used by both the FastAPI app and MCP tools
manager = ConnectionManager()
