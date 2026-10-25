# Sarissa — challenge tracking with one-way status.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

"""Challenge CRUD. Status only ever moves forward: unsolved → in_progress → solved."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Iterable

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from sarissa.api.session import SessionManager, get_manager, parse_utc, utc_now


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


def compute_score(challenges: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Score panel totals. points == 0 means unset, so only scored challenges add points."""
    items = list(challenges)
    scored = [c for c in items if c["points"] > 0]
    total = sum(c["points"] for c in scored)
    secured = sum(c["points"] for c in scored if c["status"] == Status.SOLVED.value)
    return {
        "total_points": total,
        "secured_points": secured,
        "remaining_points": total - secured,
        "solved_count": sum(1 for c in items if c["status"] == Status.SOLVED.value),
        "total_challenges": len(items),
    }


def compute_categories(challenges: Iterable[dict[str, Any]]) -> list[str]:
    """Filter bar chips: unique non-empty categories, sorted. "" means uncategorised."""
    return sorted({c["category"] for c in challenges} - {""})


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


class ScoreUpdate(BaseModel):
    # Strict: true/"100"/1.0 are not points, 1/"yes" are not solved. Omitted = unchanged.
    model_config = ConfigDict(strict=True, extra="forbid")

    point_value: StrictInt | None = Field(default=None, ge=0, le=9999)
    solved: StrictBool | None = None


class CategoryUpdate(BaseModel):
    # Any string, "" included, stored as sent — only the same 64-char cap as create/edit.
    model_config = ConfigDict(strict=True, extra="forbid")

    category: StrictStr = Field(max_length=64)


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
        "challenge_time_seconds": 0,
        "challenge_timer_started_at": None,
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


def _check_transition(challenge: dict[str, Any], new: Status) -> None:
    current = Status(challenge["status"])
    if not can_transition(current, new):
        raise HTTPException(409, f"Status cannot move backwards: {current.value} → {new.value}")


def _advance(challenge: dict[str, Any], new: Status) -> None:
    _check_transition(challenge, new)
    if new != Status(challenge["status"]):
        challenge["status"] = new.value
        if new is Status.SOLVED:
            challenge["solved_at"] = utc_now()


@router.post("/{challenge_id}/status")
def change_status(
    challenge_id: str, body: StatusChange, manager: SessionManager = Depends(get_manager)
) -> dict[str, Any]:
    challenge = _find(manager, challenge_id)
    _advance(challenge, body.status)
    return challenge


@router.patch("/{challenge_id}/score")
def update_score(
    challenge_id: str, body: ScoreUpdate, manager: SessionManager = Depends(get_manager)
) -> dict[str, Any]:
    """`point_value` is stored as `points`; `solved` is status == solved and only moves forward."""
    challenge = _find(manager, challenge_id)
    # solved: false only ever means "not solved yet" — it can never un-solve a challenge.
    if body.solved is False and challenge["status"] == Status.SOLVED.value:
        _check_transition(challenge, Status.UNSOLVED)  # raises 409 before anything is written
    if body.point_value is not None:
        challenge["points"] = body.point_value
    if body.solved:
        _advance(challenge, Status.SOLVED)
    return challenge


@router.patch("/{challenge_id}/category")
def update_category(
    challenge_id: str, body: CategoryUpdate, manager: SessionManager = Depends(get_manager)
) -> dict[str, Any]:
    challenge = _find(manager, challenge_id)
    challenge["category"] = body.category
    return challenge


def _timer_state(challenge: dict[str, Any]) -> dict[str, Any]:
    # No "current elapsed" field: the browser adds the time since started_at itself.
    return {
        "id": challenge["id"],
        "challenge_timer_started_at": challenge["challenge_timer_started_at"],
        "challenge_time_seconds": challenge["challenge_time_seconds"],
    }


@router.get("/{challenge_id}/timer")
def get_challenge_timer(challenge_id: str, manager: SessionManager = Depends(get_manager)) -> dict[str, Any]:
    return _timer_state(_find(manager, challenge_id))


@router.post("/{challenge_id}/timer/start")
def start_challenge_timer(challenge_id: str, manager: SessionManager = Depends(get_manager)) -> dict[str, Any]:
    """Idempotent: an already-running timer keeps its original start time."""
    challenge = _find(manager, challenge_id)
    if challenge["challenge_timer_started_at"] is None:
        challenge["challenge_timer_started_at"] = utc_now()
        manager.save()  # a crash never loses a running start time
    return _timer_state(challenge)


@router.post("/{challenge_id}/timer/stop")
def stop_challenge_timer(challenge_id: str, manager: SessionManager = Depends(get_manager)) -> dict[str, Any]:
    """Bank whole seconds since the last start. Idempotent: a stopped timer is left as is."""
    challenge = _find(manager, challenge_id)
    started = challenge["challenge_timer_started_at"]
    if started is not None:
        elapsed = (parse_utc(utc_now()) - parse_utc(started)).total_seconds()
        challenge["challenge_time_seconds"] += max(0, int(elapsed))
        challenge["challenge_timer_started_at"] = None
        manager.save()
    return _timer_state(challenge)


@router.delete("/{challenge_id}", status_code=204)
def delete_challenge(challenge_id: str, manager: SessionManager = Depends(get_manager)) -> Response:
    challenge = _find(manager, challenge_id)
    _challenges(manager).remove(challenge)
    return Response(status_code=204)


# GET /api/session/score and /categories live here (not in session.py) so session never
# imports challenges.
score_router = APIRouter(prefix="/api/session", tags=["challenges"])


@score_router.get("/score")
def session_score(manager: SessionManager = Depends(get_manager)) -> dict[str, int]:
    return compute_score(_challenges(manager))


@score_router.get("/categories")
def session_categories(manager: SessionManager = Depends(get_manager)) -> list[str]:
    return compute_categories(_challenges(manager))
