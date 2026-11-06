"""WebSocket: /api/ws?token=... Pushes telemetry, events, alarms, device
status, attribute and correction messages as JSON. Load /api/live first."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .auth import ws_user

router = APIRouter()


@router.websocket("/api/ws")
async def websocket(ws: WebSocket):
    user = await ws_user(ws)
    if user is None:
        await ws.close(code=4401, reason="login required")
        return
    await ws.accept()
    hub = ws.app.state.hub
    await hub.add(ws)
    try:
        await ws.send_json({"type": "hello", "user": user["username"]})
        while True:  # the client may send pings; anything else is ignored
            if await ws.receive_text() == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(ws)
