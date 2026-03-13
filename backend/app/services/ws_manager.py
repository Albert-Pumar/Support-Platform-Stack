"""
WebSocket Manager
==================
Manages active WebSocket connections from the frontend.
Broadcasts real-time ticket updates (new messages, status changes,
AI draft ready) to all connected clients — or to specific ticket rooms.
"""

import json
from collections import defaultdict
from typing import Any

import structlog
from fastapi import WebSocket

log = structlog.get_logger(__name__)


class WebSocketManager:
    def __init__(self):
        # All connected clients: set of WebSocket objects
        self._clients: set[WebSocket] = set()
        # Ticket "rooms": clients subscribed to a specific ticket
        self._ticket_rooms: defaultdict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, ticket_id: str | None = None) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        if ticket_id:
            self._ticket_rooms[ticket_id].add(websocket)
        log.info("ws.connected", ticket_id=ticket_id, total_clients=len(self._clients))

    def disconnect(self, websocket: WebSocket, ticket_id: str | None = None) -> None:
        self._clients.discard(websocket)
        if ticket_id:
            self._ticket_rooms[ticket_id].discard(websocket)
        log.info("ws.disconnected", ticket_id=ticket_id, total_clients=len(self._clients))

    async def broadcast_ticket_update(self, ticket_id: str, data: dict[str, Any]) -> None:
        """Send an update to all clients watching a specific ticket + global listeners."""
        payload = json.dumps(data)
        targets = self._ticket_rooms.get(ticket_id, set()) | self._clients

        dead = set()
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)

        # Clean up dead connections
        for ws in dead:
            self._clients.discard(ws)
            self._ticket_rooms[ticket_id].discard(ws)

    async def broadcast_global(self, data: dict[str, Any]) -> None:
        """Send an update to all connected clients (e.g. new ticket arrived)."""
        payload = json.dumps(data)
        dead = set()
        for ws in self._clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._clients.discard(ws)


# Singleton instance shared across the app
ws_manager = WebSocketManager()
