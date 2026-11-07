"""WebSocket channel `/ws/tasks/{task_id}` (spec §8.2).

Browsers cannot set an Authorization header on a WebSocket, so the access JWT travels in the
`token` query parameter and gets exactly the same checks as REST (signature, expiry, `tv`).
The socket replays the task's history on connect, then streams new events until the task is
terminal. State comes from the database, so it works with any number of workers (ADR-0010).
"""

import asyncio
import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database.models import User
from app.database.session import get_session_factory
from app.services.event_stream import TERMINAL, poll_task
from app.utils.security import decode_access_token

router = APIRouter()

WS_UNAUTHORIZED = 4401
WS_NOT_FOUND = 4404
WS_TOO_MANY = 4429

_open: defaultdict[uuid.UUID, int] = defaultdict(int)


def _user_for(factory: sessionmaker[Session], token: str | None) -> uuid.UUID | None:
    claims = decode_access_token(token or "")
    if claims is None:
        return None
    try:
        uid = uuid.UUID(str(claims["sub"]))
    except ValueError:
        return None
    with factory() as db:
        user = db.get(User, uid)
        return uid if user is not None and claims.get("tv") == user.token_version else None


@router.websocket("/ws/tasks/{task_id}")
async def task_events(
    websocket: WebSocket,
    task_id: uuid.UUID,
    token: str | None = None,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> None:
    user_id = await run_in_threadpool(_user_for, factory, token)
    if user_id is None:
        await websocket.close(code=WS_UNAUTHORIZED)
        return
    first = await run_in_threadpool(poll_task, factory, user_id, task_id)
    if first is None:  # unknown and foreign tasks look identical (no existence leak)
        await websocket.close(code=WS_NOT_FOUND)
        return
    if _open[user_id] >= settings.ws_max_connections_per_user:
        await websocket.close(code=WS_TOO_MANY)
        return
    _open[user_id] += 1
    await websocket.accept()
    sent: set[str] = set()
    try:
        result: tuple[str, list[dict[str, Any]]] | None = first
        while result is not None:
            status, events = result
            for event in events:
                if event["id"] not in sent:
                    sent.add(event["id"])
                    await websocket.send_json(event)
            if status in TERMINAL:
                await websocket.close(code=1000)
                return
            await asyncio.sleep(settings.ws_poll_seconds)
            result = await run_in_threadpool(poll_task, factory, user_id, task_id)
    except WebSocketDisconnect:
        return
    finally:
        _open[user_id] -= 1
        if _open[user_id] <= 0:
            _open.pop(user_id, None)
