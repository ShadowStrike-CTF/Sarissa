# Sarissa — challenge tracking with one-way status.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

"""Challenge CRUD. Status only ever moves forward: unsolved → in_progress → solved."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Iterable

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from sarissa.api.session import SessionManager, get_manager, utc_now


class Status(str, Enum):
    UNSOLVED = "unsolved"
    IN_PROGRESS = "in_progress"
    SOLVED = "solved"


_RANK = {Status.UNSOLVED: 0, Status.IN_PROGRESS: 1, Status.SOLVED: 2}


def can_transition(current: Status | str, new: Status | str) -> bool:
    """Forward moves (including skipping ahead) and no-ops are allowed; backwards never."""
    return _RANK[Status(new)] >= _RANK[Status(current)]


def compute_tally(challenges: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Point tally is always derived from challenge data, never stored."""
    items = list(challenges)
    solved = [c for c in items if c["status"] == Status.SOLVED.value]
    return {
        "earned": sum(c["points"] for c in solved),
        "total": sum(c["points"] for c in items),
        "solved": len(solved),
        "in_progress": sum(1 for c in items if c["status"] == Status.IN_PROGRESS.value),
        "count": len(items),
    }


# --- API -------------------------------------------------------------------

router = APIRouter(prefix="/api/challenges", tags=["challenges"])


class ChallengeCreate(BaseModel):
    # Any client-supplied "status" is ignored: new challenges always start unsolved.
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="", max_length=64)
    points: int = Field(default=0, ge=0)
    notes: str = Field(default="", max_length=10_000)


class ChallengeUpdate(BaseModel):
    # extra="forbid": status cannot sneak in through an edit.
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=64)
    points: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=10_000)


class StatusChange(BaseModel):
    status: Status


def _challenges(manager: SessionManager) -> list[dict[str, Any]]:
    return manager.require_current()["challenges"]


def _find(manager: SessionManager, challenge_id: str) -> dict[str, Any]:
    for c in _challenges(manager):
        if c["id"] == challenge_id:
            return c
    raise HTTPException(404, f"Challenge {challenge_id!r} not found")


@router.get("")
def list_challenges(manager: SessionManager = Depends(get_manager)) -> dict[str, Any]:
    items = _challenges(manager)
    return {"challenges": items, "tally": compute_tally(items)}


@router.post("", status_code=201)
def create_challenge(body: ChallengeCreate, manager: SessionManager = Depends(get_manager)) -> dict[str, Any]:
    challenge = {
        "id": uuid.uuid4().hex[:12],
        **body.model_dump(),
        "status": Status.UNSOLVED.value,
        "created_at": utc_now(),
        "solved_at": None,
    }
    _challenges(manager).append(challenge)
    return challenge


@router.patch("/{challenge_id}")
def update_challenge(
    challenge_id: str, body: ChallengeUpdate, manager: SessionManager = Depends(get_manager)
) -> dict[str, Any]:
    challenge = _find(manager, challenge_id)
    challenge.update(body.model_dump(exclude_none=True))
    return challenge


@router.post("/{challenge_id}/status")
def change_status(
    challenge_id: str, body: StatusChange, manager: SessionManager = Depends(get_manager)
) -> dict[str, Any]:
    challenge = _find(manager, challenge_id)
    current = Status(challenge["status"])
    if not can_transition(current, body.status):
        raise HTTPException(
            409, f"Status cannot move backwards: {current.value} → {body.status.value}"
        )
    if body.status != current:
        challenge["status"] = body.status.value
        if body.status is Status.SOLVED:
            challenge["solved_at"] = utc_now()
    return challenge


@router.delete("/{challenge_id}", status_code=204)
def delete_challenge(challenge_id: str, manager: SessionManager = Depends(get_manager)) -> Response:
    challenge = _find(manager, challenge_id)
    _challenges(manager).remove(challenge)
    return Response(status_code=204)
