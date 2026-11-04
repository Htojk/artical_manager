"""Server-sent events for workflow progress."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.events import event_bus

router = APIRouter(tags=["events"])

HEARTBEAT_SECONDS = 15.0


@router.get("/events")
async def stream_events(request: Request) -> StreamingResponse:
    queue = event_bus.subscribe()

    async def generator():
        try:
            yield _frame({"type": "connected"})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield _frame(event.as_dict())
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _frame(payload: dict) -> str:
    return f"event: {payload.get('type', 'message')}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
