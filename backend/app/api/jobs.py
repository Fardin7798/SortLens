"""Job API: start a long step, watch it live (SSE), stop it.

POST /api/jobs                {"kind": "...", "params": {...}}  -> 202 job
GET  /api/jobs                recent jobs
GET  /api/jobs/{id}           one job
GET  /api/jobs/{id}/events    text/event-stream: `progress` events, then one `end`
POST /api/jobs/{id}/stop      stop at the next batch (work done so far is kept)
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.jobs import KINDS, Busy, manager

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
POLL = 0.25
HEARTBEAT = 15.0


class JobIn(BaseModel):
    kind: str = Field(description=" | ".join(KINDS))
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("", status_code=202)
def start(body: JobIn) -> dict[str, Any]:
    try:
        return manager().start(body.kind, body.params).view()
    except Busy as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("")
def recent(limit: int = 20) -> list[dict[str, Any]]:
    return manager().recent(max(1, min(limit, 100)))


@router.get("/{jid}")
def one(jid: int) -> dict[str, Any]:
    job = manager().get(jid)
    if not job:
        raise HTTPException(404, "no such job")
    return job.view()


@router.post("/{jid}/stop", status_code=202)
def stop(jid: int) -> dict[str, Any]:
    job = manager().stop(jid)
    if not job:
        raise HTTPException(404, "no such job")
    return job.view()


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/{jid}/events")
async def events(jid: int) -> StreamingResponse:
    m = manager()
    if not m.get(jid):
        raise HTTPException(404, "no such job")

    async def stream() -> AsyncIterator[str]:
        seen, idle = -1, 0.0
        while True:
            job = m.get(jid)
            assert job is not None
            if job.status != "running":
                yield _sse("end", job.view())
                return
            if job.seq != seen:
                seen, idle = job.seq, 0.0
                yield _sse("progress", {"id": jid, "progress": job.progress})
            elif idle >= HEARTBEAT:
                idle = 0.0
                yield ": keep-alive\n\n"
            await asyncio.sleep(POLL)
            idle += POLL

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )  # fmt: skip
