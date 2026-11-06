"""WebSocket fan-out to connected dashboards."""
import asyncio
import logging

from fastapi import WebSocket

from .db import dumps

log = logging.getLogger(__name__)


class Hub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def add(self, ws: WebSocket) -> None:
        self._clients.add(ws)

    def remove(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    @property
    def count(self) -> int:
        return len(self._clients)

    async def broadcast(self, message: dict) -> None:
        if not self._clients:
            return
        text = dumps(message)
        dead = []
        for ws in list(self._clients):
            try:
                await asyncio.wait_for(ws.send_text(text), timeout=2)
            except Exception:  # client gone or too slow
                dead.append(ws)
        for ws in dead:
            self.remove(ws)
