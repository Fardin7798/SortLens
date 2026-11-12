"""Review API. Building a plan changes nothing; files move only on apply with the plan's code.

POST /api/plans               build a plan -> its full list + confirm code
     {"kind": "trash", "from_dupes": {"run": 1, "kinds": ["exact"]}}
     {"kind": "move", "from_solo": {"run": 2, "buckets": ["solo"]}, "dest": "Fardin akela"}
     {"kind": "trash" | "move", "media_ids": [1, 2], "dest": "..."}
GET  /api/plans               recent plans
GET  /api/plans/{id}          one plan with every item
POST /api/plans/{id}/apply    {"code": "..."} -> a job (watch /api/jobs/{job}/events)
POST /api/plans/{id}/undo     {"code": "..."} -> a job that moves everything back
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core import plans
from app.core.config import settings
from app.core.jobs import Busy, manager
from app.db import store

router = APIRouter(prefix="/api/plans", tags=["review"])


class FromSolo(BaseModel):
    run: int
    buckets: list[str] = Field(default_factory=lambda: ["solo"])


class FromDupes(BaseModel):
    run: int
    kinds: list[str] = Field(default_factory=lambda: ["exact"])


class PlanIn(BaseModel):
    kind: str
    dest: str = ""
    media_ids: list[int] = Field(default_factory=list)
    from_solo: FromSolo | None = None
    from_dupes: FromDupes | None = None


class CodeIn(BaseModel):
    code: str


@router.post("", status_code=201)
def create(body: PlanIn) -> dict[str, Any]:
    con = store.connect(settings.db_path)
    try:
        dest = Path(body.dest) if body.dest else None
        if body.from_solo:
            if body.kind != "move" or not dest:
                raise plans.PlanError("a solo list is moved: kind=move and a dest folder")
            pid = plans.from_solo(con, body.from_solo.run, dest=dest,
                                  buckets=tuple(body.from_solo.buckets))  # fmt: skip
        elif body.from_dupes:
            if body.kind != "trash":
                raise plans.PlanError("duplicate extras go to SortLens Trash: kind=trash")
            pid = plans.from_dupes(con, body.from_dupes.run, kinds=tuple(body.from_dupes.kinds))
        else:
            pid = plans.create(con, body.media_ids, kind=body.kind, dest=dest)
        out = plans.get(con, pid)
        assert out is not None
        return out
    except plans.PlanError as e:
        raise HTTPException(422, str(e)) from e
    finally:
        con.close()


@router.get("")
def recent(limit: int = 20) -> list[dict[str, Any]]:
    con = store.connect(settings.db_path)
    try:
        return plans.recent(con, max(1, min(limit, 100)))
    finally:
        con.close()


@router.get("/{pid}")
def one(pid: int) -> dict[str, Any]:
    con = store.connect(settings.db_path)
    try:
        p = plans.get(con, pid)
    finally:
        con.close()
    if not p:
        raise HTTPException(404, "no such plan")
    return p


def _job(kind: str, pid: int, code: str) -> dict[str, Any]:
    try:
        return manager().start(kind, {"plan": pid, "code": code}).view()
    except Busy as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/{pid}/apply", status_code=202)
def apply(pid: int, body: CodeIn) -> dict[str, Any]:
    return _job("apply_plan", pid, body.code)


@router.post("/{pid}/undo", status_code=202)
def undo(pid: int, body: CodeIn) -> dict[str, Any]:
    return _job("undo_plan", pid, body.code)
