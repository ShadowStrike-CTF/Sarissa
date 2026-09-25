# Sarissa — named session management with 60-second auto-save.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

"""One JSON file per competition at ~/.sarissa/sessions/<name>.json."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger("sarissa.session")

SESSIONS_DIR = Path.home() / ".sarissa" / "sessions"
AUTOSAVE_INTERVAL = 60  # seconds — fixed by CLAUDE.md
DEFAULT_SESSION = "default"
NAME_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_NAME_RE = re.compile(NAME_PATTERN)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_name(name: str) -> str:
    """Session names become file names, so only a safe charset is allowed."""
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise ValueError(
            f"Invalid session name {name!r}: use 1-64 letters, digits, '-' or '_'"
        )
    return name


def new_session_data(name: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "name": name,
        "created_at": now,
        "updated_at": now,
        "challenges": [],
        "timer": {"mode": "countdown", "duration_seconds": 0, "started_at": None},
    }


class SessionManager:
    """Holds the active session in memory and persists it to disk."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else SESSIONS_DIR
        self.current: dict[str, Any] | None = None
        self.last_saved: str | None = None

    def path_for(self, name: str) -> Path:
        return self.base_dir / f"{validate_name(name)}.json"

    def exists(self, name: str) -> bool:
        return self.path_for(name).is_file()

    def list(self) -> list[str]:
        if not self.base_dir.is_dir():
            return []
        return sorted(p.stem for p in self.base_dir.glob("*.json") if _NAME_RE.fullmatch(p.stem))

    def create(self, name: str) -> dict[str, Any]:
        if self.exists(name):
            raise FileExistsError(f"Session {name!r} already exists")
        self.save()  # never lose the session being switched away from
        self.current = new_session_data(name)
        self.save()
        return self.current

    def load(self, name: str) -> dict[str, Any]:
        path = self.path_for(name)
        if not path.is_file():
            raise FileNotFoundError(f"Session {name!r} not found")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.save()
        self.current = data
        self.last_saved = data.get("updated_at")
        return self.current

    def open(self, name: str) -> dict[str, Any]:
        """Restore a session if it exists, otherwise create it (startup path)."""
        return self.load(name) if self.exists(name) else self.create(name)

    def save(self) -> str | None:
        if self.current is None:
            return None
        self.current["updated_at"] = utc_now()
        path = self.path_for(self.current["name"])
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.current, indent=2), encoding="utf-8")
        os.replace(tmp, path)  # atomic: a crash mid-write never corrupts the session
        self.last_saved = self.current["updated_at"]
        return self.last_saved

    def require_current(self) -> dict[str, Any]:
        if self.current is None:
            raise RuntimeError("No active session")
        return self.current


async def autosave_loop(manager: SessionManager, interval: float = AUTOSAVE_INTERVAL) -> None:
    """Background task: save the active session every `interval` seconds."""
    while True:
        await asyncio.sleep(interval)
        try:
            manager.save()
        except OSError:
            log.exception("Auto-save failed")


def get_manager(request: Request) -> SessionManager:
    return request.app.state.sessions


# --- API -------------------------------------------------------------------

router = APIRouter(prefix="/api/session", tags=["session"])


class SessionCreate(BaseModel):
    name: str = Field(pattern=NAME_PATTERN)


class TimerUpdate(BaseModel):
    mode: Literal["countdown", "elapsed"] | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    action: Literal["start", "reset"] | None = None


def _summary(manager: SessionManager) -> dict[str, Any]:
    data = manager.require_current()
    return {
        "name": data["name"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "timer": data["timer"],
        "last_saved": manager.last_saved,
        "autosave_interval": AUTOSAVE_INTERVAL,
        "server_time": utc_now(),
    }


@router.get("")
def current_session(manager: SessionManager = Depends(get_manager)) -> dict[str, Any]:
    return _summary(manager)


@router.get("/list")
def list_sessions(manager: SessionManager = Depends(get_manager)) -> dict[str, Any]:
    return {"sessions": manager.list(), "current": manager.require_current()["name"]}


@router.post("", status_code=201)
def create_session(body: SessionCreate, manager: SessionManager = Depends(get_manager)) -> dict[str, Any]:
    try:
        manager.create(body.name)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _summary(manager)


@router.post("/save")
def save_session(manager: SessionManager = Depends(get_manager)) -> dict[str, Any]:
    return {"saved_at": manager.save()}


@router.post("/{name}/load")
def load_session(name: str, manager: SessionManager = Depends(get_manager)) -> dict[str, Any]:
    try:
        manager.load(name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _summary(manager)


@router.put("/timer")
def update_timer(body: TimerUpdate, manager: SessionManager = Depends(get_manager)) -> dict[str, Any]:
    timer = manager.require_current()["timer"]
    if body.mode is not None:
        timer["mode"] = body.mode
    if body.duration_seconds is not None:
        timer["duration_seconds"] = body.duration_seconds
    if body.action == "start":
        timer["started_at"] = utc_now()
    elif body.action == "reset":
        timer["started_at"] = None
    return timer
