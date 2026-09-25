# Sarissa — named session create / restore / isolation and auto-save.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sarissa.api import session
from sarissa.api.session import SessionManager, autosave_loop, timer_status, validate_name
from sarissa.main import PORT, create_app


@pytest.fixture
def bare_client(tmp_path):
    """App as launched: no session open until the picker creates or restores one."""
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        yield c


@pytest.fixture
def client(bare_client):
    assert bare_client.post("/api/session", json={"name": "comp"}).status_code == 201
    return bare_client


def add(client, name, points=100):
    return client.post("/api/challenges", json={"name": name, "points": points}).json()


def names(client):
    return [c["name"] for c in client.get("/api/challenges").json()["challenges"]]


def test_invariants():
    assert PORT == 7331
    assert session.AUTOSAVE_INTERVAL == 60
    assert session.URGENT_THRESHOLD == 30 * 60
    assert session.SESSIONS_DIR == Path.home() / ".sarissa" / "sessions"


def test_no_session_created_on_startup(bare_client, tmp_path):
    assert list(tmp_path.iterdir()) == []
    assert bare_client.get("/api/session/recent").json() == {"sessions": [], "current": None}
    assert bare_client.get("/api/session/list").json() == {"sessions": [], "current": None}
    assert bare_client.get("/api/session").status_code == 409
    assert bare_client.get("/api/challenges").status_code == 409
    assert bare_client.get("/api/session/timer").status_code == 409
    assert bare_client.post("/api/session/save").json() == {"saved_at": None}
    assert list(tmp_path.iterdir()) == []


def test_create_named_session(client, tmp_path):
    r = client.post("/api/session", json={"name": "ductf-2026"})
    assert r.status_code == 201 and r.json()["name"] == "ductf-2026"
    data = json.loads((tmp_path / "ductf-2026.json").read_text())
    assert data["name"] == "ductf-2026" and data["challenges"] == []
    assert client.get("/api/session/list").json() == {"sessions": ["comp", "ductf-2026"], "current": "ductf-2026"}


def test_duplicate_session_rejected(client):
    assert client.post("/api/session", json={"name": "a"}).status_code == 201
    assert client.post("/api/session", json={"name": "a"}).status_code == 409


@pytest.mark.parametrize("bad", ["../evil", "a/b", "", "x" * 65, "sp ace", "dot.json"])
def test_invalid_names_rejected(client, bad):
    assert client.post("/api/session", json={"name": bad}).status_code == 422
    with pytest.raises(ValueError):
        validate_name(bad)


def test_load_missing_session_404(client):
    assert client.post("/api/session/ghost/load").status_code == 404


def test_sessions_isolated(client):
    client.post("/api/session", json={"name": "comp-a"})
    add(client, "a-disk")
    client.post("/api/session", json={"name": "comp-b"})
    assert names(client) == []
    add(client, "b-memory")

    client.post("/api/session/comp-a/load")
    assert names(client) == ["a-disk"]
    client.post("/api/session/comp-b/load")
    assert names(client) == ["b-memory"]


def test_restore_after_restart(tmp_path):
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        c.post("/api/session", json={"name": "comp"})
        cid = add(c, "persist-me", 300)["id"]
        c.post(f"/api/challenges/{cid}/status", json={"status": "solved"})
        c.put("/api/session/timer", json={"duration_seconds": 7200, "action": "start"})
    # Shutdown saves; a fresh app restores the same named session via the picker.
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        assert c.get("/api/session/recent").json()["current"] is None
        assert c.post("/api/session/comp/load").status_code == 200
        body = c.get("/api/challenges").json()
        assert [x["name"] for x in body["challenges"]] == ["persist-me"]
        assert body["tally"]["earned"] == 300
        timer = c.get("/api/session").json()["timer"]
        assert timer["duration_seconds"] == 7200 and timer["started_at"] is not None


def test_manager_restore_direct(tmp_path):
    m = SessionManager(tmp_path)
    m.create("x")
    m.current["challenges"].append({"id": "1", "name": "n", "points": 1, "status": "unsolved"})
    m.save()
    m2 = SessionManager(tmp_path)
    assert m2.load("x")["challenges"][0]["name"] == "n"
    with pytest.raises(ValueError):
        m2.load("../x")


def test_switching_saves_previous_session(tmp_path):
    m = SessionManager(tmp_path)
    m.create("first")
    m.current["challenges"].append({"id": "1"})
    m.create("second")  # switch without an explicit save
    assert json.loads((tmp_path / "first.json").read_text())["challenges"] == [{"id": "1"}]


def test_timer_modes(client):
    r = client.put("/api/session/timer", json={"mode": "elapsed", "duration_seconds": 3600})
    assert r.json() == {"mode": "elapsed", "duration_seconds": 3600, "started_at": None}
    assert client.put("/api/session/timer", json={"action": "start"}).json()["started_at"] is not None
    assert client.put("/api/session/timer", json={"action": "reset"}).json()["started_at"] is None
    assert client.put("/api/session/timer", json={"mode": "sideways"}).status_code == 422


def test_explicit_save(client, tmp_path):
    add(client, "saved")
    r = client.post("/api/session/save")
    assert r.json()["saved_at"]
    assert json.loads((tmp_path / "comp.json").read_text())["challenges"][0]["name"] == "saved"


def test_autosave_loop_writes_to_disk(tmp_path):
    m = SessionManager(tmp_path)
    m.create("auto")
    m.current["challenges"].append({"id": "z", "name": "autosaved"})

    async def run():
        task = asyncio.create_task(autosave_loop(m, interval=0.01))
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(run())
    data = json.loads((tmp_path / "auto.json").read_text())
    assert data["challenges"] == [{"id": "z", "name": "autosaved"}]


def test_autosave_default_interval():
    import inspect

    assert inspect.signature(autosave_loop).parameters["interval"].default == 60


# --- Phase 3: timer urgency + persistence ------------------------------------

def iso(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def set_timer(client, **timer):
    client.app.state.sessions.current["timer"] = {
        "mode": "countdown", "duration_seconds": 0, "started_at": None, **timer,
    }


def test_timer_urgency_applied(client):
    now = datetime.now(timezone.utc)
    # 60-minute countdown started 31 minutes ago → 29 minutes left.
    set_timer(client, duration_seconds=3600, started_at=iso(now - timedelta(minutes=31)))
    body = client.get("/api/session/timer").json()
    assert body["urgent"] is True and 0 < body["remaining_seconds"] < 30 * 60
    assert body["mode"] == "countdown" and body["duration_seconds"] == 3600

    # 31 minutes left → not yet urgent.
    set_timer(client, duration_seconds=3600, started_at=iso(now - timedelta(minutes=29)))
    assert client.get("/api/session/timer").json()["urgent"] is False

    # Overtime is still urgent; a countdown that hasn't started is not.
    set_timer(client, duration_seconds=600, started_at=iso(now - timedelta(minutes=20)))
    assert client.get("/api/session/timer").json()["urgent"] is True
    set_timer(client, duration_seconds=600)
    assert client.get("/api/session/timer").json()["urgent"] is False

    # Urgency is derived, never stored in the session JSON.
    client.post("/api/session/save")
    assert "urgent" not in client.app.state.sessions.current["timer"]


def test_timer_urgency_not_elapsed(client):
    now = datetime.now(timezone.utc)
    for started in (now - timedelta(minutes=31), now - timedelta(hours=5), now):
        set_timer(client, mode="elapsed", duration_seconds=3600, started_at=iso(started))
        body = client.get("/api/session/timer").json()
        assert body["urgent"] is False and body["remaining_seconds"] is None
    timer = {"mode": "elapsed", "duration_seconds": 60, "started_at": iso(now - timedelta(hours=1))}
    assert timer_status(timer, now)["urgent"] is False
    assert timer_status({**timer, "mode": "countdown"}, now)["urgent"] is True


def test_timer_refresh_persistence(client, tmp_path):
    timer = {"mode": "countdown", "duration_seconds": 7200, "started_at": "2026-09-25T10:00:00Z"}
    stored = session.new_session_data("comp2")
    stored["timer"] = dict(timer)
    (tmp_path / "comp2.json").write_text(json.dumps(stored))

    assert client.post("/api/session/comp2/load").json()["timer"] == timer
    assert client.get("/api/session").json()["timer"] == timer
    got = client.get("/api/session/timer").json()
    assert {k: got[k] for k in timer} == timer

    # Toggling mode is written to the session JSON immediately (survives a refresh or restart).
    client.put("/api/session/timer", json={"mode": "elapsed"})
    on_disk = json.loads((tmp_path / "comp2.json").read_text())["timer"]
    assert on_disk == {**timer, "mode": "elapsed"}
    with TestClient(create_app(sessions_dir=tmp_path)) as fresh:
        assert fresh.post("/api/session/comp2/load").json()["timer"] == {**timer, "mode": "elapsed"}


# --- Phase 3: session picker ------------------------------------------------

def write_session(tmp_path, name, updated_at):
    data = session.new_session_data(name)
    data["updated_at"] = updated_at
    (tmp_path / f"{name}.json").write_text(json.dumps(data))


def test_session_picker_order(bare_client, tmp_path):
    write_session(tmp_path, "A", "2026-09-24T09:00:00Z")  # older
    write_session(tmp_path, "B", "2026-09-25T14:32:00Z")  # newer
    body = bare_client.get("/api/session/recent").json()
    assert body == {
        "sessions": [
            {"name": "B", "last_saved": "2026-09-25T14:32:00Z"},
            {"name": "A", "last_saved": "2026-09-24T09:00:00Z"},
        ],
        "current": None,
    }


def test_session_picker_limit_and_corrupt_file(bare_client, tmp_path):
    for i in range(12):
        write_session(tmp_path, f"s{i:02d}", f"2026-09-{10 + i:02d}T12:00:00Z")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")  # falls back to the file's mtime, pinned here → newest
    stamp = datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp()
    os.utime(broken, (stamp, stamp))
    rows = bare_client.get("/api/session/recent").json()["sessions"]
    assert len(rows) == 10
    assert [r["name"] for r in rows] == ["broken"] + [f"s{i:02d}" for i in range(11, 2, -1)]
    assert rows[0]["last_saved"] == "2026-09-30T00:00:00Z"


@pytest.mark.parametrize("body", [{"name": ""}, {"name": "   "}, {"name": "\t\n"}, {}])
def test_session_picker_empty_name(bare_client, tmp_path, body):
    assert bare_client.post("/api/session", json=body).status_code == 422
    assert list(tmp_path.iterdir()) == []


def test_session_name_trimmed(bare_client, tmp_path):
    assert bare_client.post("/api/session", json={"name": "  ductf  "}).json()["name"] == "ductf"
    assert (tmp_path / "ductf.json").is_file()
