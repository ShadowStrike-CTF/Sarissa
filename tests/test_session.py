# Sarissa — named session create / restore / isolation and auto-save.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sarissa.api import session
from sarissa.api.session import SessionManager, autosave_loop, validate_name
from sarissa.main import PORT, create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        yield c


def add(client, name, points=100):
    return client.post("/api/challenges", json={"name": name, "points": points}).json()


def names(client):
    return [c["name"] for c in client.get("/api/challenges").json()["challenges"]]


def test_invariants():
    assert PORT == 7331
    assert session.AUTOSAVE_INTERVAL == 60
    assert session.SESSIONS_DIR == Path.home() / ".sarissa" / "sessions"


def test_default_session_created_on_startup(client, tmp_path):
    assert client.get("/api/session").json()["name"] == "default"
    assert (tmp_path / "default.json").is_file()


def test_create_named_session(client, tmp_path):
    r = client.post("/api/session", json={"name": "ductf-2026"})
    assert r.status_code == 201 and r.json()["name"] == "ductf-2026"
    data = json.loads((tmp_path / "ductf-2026.json").read_text())
    assert data["name"] == "ductf-2026" and data["challenges"] == []
    assert client.get("/api/session/list").json() == {"sessions": ["default", "ductf-2026"], "current": "ductf-2026"}


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
    with TestClient(create_app(sessions_dir=tmp_path, session_name="comp")) as c:
        cid = add(c, "persist-me", 300)["id"]
        c.post(f"/api/challenges/{cid}/status", json={"status": "solved"})
        c.put("/api/session/timer", json={"duration_seconds": 7200, "action": "start"})
    # Shutdown saves; a fresh app restores the same named session.
    with TestClient(create_app(sessions_dir=tmp_path, session_name="comp")) as c:
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
    assert json.loads((tmp_path / "default.json").read_text())["challenges"][0]["name"] == "saved"


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
