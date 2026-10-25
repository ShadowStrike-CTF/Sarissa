# Sarissa — Phase 13 per-challenge timer (start/stop/GET, export schema v1.3).
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import json

import pytest
from fastapi.testclient import TestClient

from sarissa.api import challenges
from sarissa.main import create_app

KEYS = {"id", "challenge_timer_started_at", "challenge_time_seconds"}


@pytest.fixture
def bare_client(tmp_path):
    """App as launched: no session open until the picker creates or restores one."""
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        yield c


@pytest.fixture
def client(bare_client):
    assert bare_client.post("/api/session", json={"name": "comp"}).status_code == 201
    return bare_client


@pytest.fixture
def clock(monkeypatch):
    """Server time for the challenge timer routes; set clock.now to move it."""
    class Clock:
        now = "2026-10-25T10:00:00Z"

    monkeypatch.setattr(challenges, "utc_now", lambda: Clock.now)
    return Clock


def add(client, name="chal"):
    r = client.post("/api/challenges", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


def timer(client, cid, action=None):
    if action is None:
        return client.get(f"/api/challenges/{cid}/timer")
    return client.post(f"/api/challenges/{cid}/timer/{action}")


def saved_challenge(tmp_path, cid):
    data = json.loads((tmp_path / "comp.json").read_text(encoding="utf-8"))
    return next(c for c in data["challenges"] if c["id"] == cid)


def test_timer_start_sets_timestamp(client, clock, tmp_path):
    cid = add(client)
    r = timer(client, cid, "start")
    assert r.status_code == 200
    assert r.json() == {"id": cid, "challenge_timer_started_at": "2026-10-25T10:00:00Z",
                        "challenge_time_seconds": 0}
    # Persisted immediately, not only on the next auto-save.
    assert saved_challenge(tmp_path, cid)["challenge_timer_started_at"] == "2026-10-25T10:00:00Z"


def test_timer_stop_accumulates_seconds(client, clock, tmp_path):
    cid = add(client)
    timer(client, cid, "start")
    clock.now = "2026-10-25T10:01:30Z"
    r = timer(client, cid, "stop")
    assert r.status_code == 200
    assert r.json() == {"id": cid, "challenge_timer_started_at": None, "challenge_time_seconds": 90}
    # A second run adds to the banked total.
    clock.now = "2026-10-25T11:00:00Z"
    timer(client, cid, "start")
    clock.now = "2026-10-25T11:00:15Z"
    assert timer(client, cid, "stop").json()["challenge_time_seconds"] == 105
    stored = saved_challenge(tmp_path, cid)
    assert stored["challenge_time_seconds"] == 105 and stored["challenge_timer_started_at"] is None


def test_timer_stop_idempotent(client, clock):
    cid = add(client)
    # Stop on a never-started timer: current state, no error.
    assert timer(client, cid, "stop").json() == {
        "id": cid, "challenge_timer_started_at": None, "challenge_time_seconds": 0}
    timer(client, cid, "start")
    clock.now = "2026-10-25T10:00:10Z"
    first = timer(client, cid, "stop").json()
    clock.now = "2026-10-25T10:05:00Z"
    second = timer(client, cid, "stop")
    assert second.status_code == 200 and second.json() == first
    assert first["challenge_time_seconds"] == 10


def test_timer_start_idempotent(client, clock):
    cid = add(client)
    first = timer(client, cid, "start").json()
    clock.now = "2026-10-25T10:02:00Z"
    second = timer(client, cid, "start")
    assert second.status_code == 200 and second.json() == first
    # The original start time is kept, so the full span is banked on stop.
    assert timer(client, cid, "stop").json()["challenge_time_seconds"] == 120


def test_timer_get_state(client, clock):
    cid = add(client)
    r = timer(client, cid)
    assert r.status_code == 200
    assert r.json() == {"id": cid, "challenge_timer_started_at": None, "challenge_time_seconds": 0}
    timer(client, cid, "start")
    clock.now = "2026-10-25T10:00:42Z"
    state = timer(client, cid).json()
    # No server-side "current elapsed": only the stored fields come back.
    assert set(state) == KEYS
    assert state["challenge_timer_started_at"] == "2026-10-25T10:00:00Z"
    assert state["challenge_time_seconds"] == 0
    for action in (None, "start", "stop"):
        assert timer(client, "nope", action).status_code == 404
    # The list route carries the same stored fields; edits cannot set them.
    listed = client.get("/api/challenges").json()["challenges"][0]
    assert listed["challenge_timer_started_at"] == "2026-10-25T10:00:00Z"
    assert client.patch(f"/api/challenges/{cid}", json={"challenge_time_seconds": 999}).status_code == 422


def test_export_schema_v1_3(client, clock, tmp_path):
    cid = add(client, "memory dump")
    timer(client, cid, "start")
    clock.now = "2026-10-25T10:00:30Z"
    timer(client, cid, "stop")
    timer(client, cid, "start")  # running at export time
    data = client.get("/api/export").json()
    assert data["schema_version"] == "1.3"
    chal = data["challenges"][0]
    assert chal["challenge_time_seconds"] == 30
    assert "challenge_timer_started_at" not in chal
    # Stripping is export-only: the stored challenge keeps its running start time.
    assert timer(client, cid).json()["challenge_timer_started_at"] == "2026-10-25T10:00:30Z"
    # A pre-Phase-13 session file is backfilled on load, so its export still has the field.
    old = dict(saved_challenge(tmp_path, cid), id="old1")
    del old["challenge_time_seconds"], old["challenge_timer_started_at"]
    session_file = json.loads((tmp_path / "comp.json").read_text(encoding="utf-8"))
    (tmp_path / "legacy.json").write_text(json.dumps({**session_file, "name": "legacy", "challenges": [old]}))
    assert client.post("/api/session/legacy/load").status_code == 200
    legacy = client.get("/api/export").json()["challenges"][0]
    assert legacy["challenge_time_seconds"] == 0 and "challenge_timer_started_at" not in legacy


def test_timer_independent_of_session_timer(client, clock):
    cid = add(client)
    session_timer = client.get("/api/session/timer").json()
    timer(client, cid, "start")
    clock.now = "2026-10-25T10:00:05Z"
    timer(client, cid, "stop")
    assert client.get("/api/session/timer").json() == session_timer
    # And the reverse: starting/resetting the session timer leaves the challenge timer alone.
    timer(client, cid, "start")
    before = timer(client, cid).json()
    assert client.put("/api/session/timer", json={"action": "start"}).status_code == 200
    assert client.put("/api/session/timer", json={"action": "reset"}).status_code == 200
    assert timer(client, cid).json() == before


def test_timer_409_no_session(bare_client):
    for action in (None, "start", "stop"):
        assert timer(bare_client, "x", action).status_code == 409
