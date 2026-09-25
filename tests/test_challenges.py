# Sarissa — challenge status one-way enforcement and point tally.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import json

import pytest
from fastapi.testclient import TestClient

from sarissa.api.challenges import Status, can_transition, compute_tally
from sarissa.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        # No session exists at launch; challenges need one.
        assert c.post("/api/session", json={"name": "comp"}).status_code == 201
        yield c


def add(client, name="chal", points=100, **extra):
    r = client.post("/api/challenges", json={"name": name, "points": points, **extra})
    assert r.status_code == 201
    return r.json()


def set_status(client, cid, status):
    return client.post(f"/api/challenges/{cid}/status", json={"status": status})


# --- one-way status ---------------------------------------------------------

@pytest.mark.parametrize(
    "current,new,allowed",
    [
        ("unsolved", "unsolved", True),
        ("unsolved", "in_progress", True),
        ("unsolved", "solved", True),
        ("in_progress", "unsolved", False),
        ("in_progress", "in_progress", True),
        ("in_progress", "solved", True),
        ("solved", "unsolved", False),
        ("solved", "in_progress", False),
        ("solved", "solved", True),
    ],
)
def test_can_transition_truth_table(current, new, allowed):
    assert can_transition(current, new) is allowed
    assert can_transition(Status(current), Status(new)) is allowed


def test_new_challenge_starts_unsolved(client):
    assert add(client)["status"] == "unsolved"


def test_create_ignores_client_supplied_status(client):
    c = add(client, status="solved")
    assert c["status"] == "unsolved"
    assert c["solved_at"] is None


def test_forward_transitions(client):
    cid = add(client)["id"]
    r = set_status(client, cid, "in_progress")
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    r = set_status(client, cid, "solved")
    assert r.status_code == 200 and r.json()["status"] == "solved"
    assert r.json()["solved_at"] is not None


def test_skip_ahead_unsolved_to_solved(client):
    cid = add(client)["id"]
    assert set_status(client, cid, "solved").json()["status"] == "solved"


def test_same_status_is_noop(client):
    cid = add(client)["id"]
    set_status(client, cid, "in_progress")
    r = set_status(client, cid, "in_progress")
    assert r.status_code == 200 and r.json()["status"] == "in_progress"


@pytest.mark.parametrize(
    "path,backwards",
    [
        (["in_progress"], "unsolved"),
        (["solved"], "in_progress"),
        (["solved"], "unsolved"),
        (["in_progress", "solved"], "in_progress"),
    ],
)
def test_backward_transitions_rejected(client, path, backwards):
    cid = add(client)["id"]
    for s in path:
        assert set_status(client, cid, s).status_code == 200
    r = set_status(client, cid, backwards)
    assert r.status_code == 409
    listed = client.get("/api/challenges").json()["challenges"]
    assert listed[0]["status"] == path[-1]  # state unchanged


def test_invalid_status_rejected(client):
    cid = add(client)["id"]
    assert set_status(client, cid, "done").status_code == 422


def test_patch_cannot_change_status(client):
    cid = add(client)["id"]
    set_status(client, cid, "solved")
    r = client.patch(f"/api/challenges/{cid}", json={"status": "unsolved"})
    assert r.status_code == 422
    assert client.get("/api/challenges").json()["challenges"][0]["status"] == "solved"


def test_patch_updates_fields(client):
    cid = add(client, category="disk")["id"]
    r = client.patch(f"/api/challenges/{cid}", json={"points": 250, "notes": "check $MFT"})
    assert r.status_code == 200
    assert r.json()["points"] == 250 and r.json()["notes"] == "check $MFT"
    assert r.json()["category"] == "disk"


def test_negative_points_rejected(client):
    assert client.post("/api/challenges", json={"name": "x", "points": -5}).status_code == 422


def test_unknown_challenge_404(client):
    assert set_status(client, "nope", "solved").status_code == 404
    assert client.patch("/api/challenges/nope", json={"points": 1}).status_code == 404
    assert client.delete("/api/challenges/nope").status_code == 404


def test_delete(client):
    cid = add(client)["id"]
    assert client.delete(f"/api/challenges/{cid}").status_code == 204
    assert client.get("/api/challenges").json()["challenges"] == []


# --- point tally ------------------------------------------------------------

def test_compute_tally_pure():
    items = [
        {"points": 100, "status": "solved"},
        {"points": 200, "status": "in_progress"},
        {"points": 300, "status": "unsolved"},
        {"points": 50, "status": "solved"},
    ]
    assert compute_tally(items) == {"earned": 150, "total": 650, "solved": 2, "in_progress": 1, "count": 4}
    assert compute_tally([]) == {"earned": 0, "total": 0, "solved": 0, "in_progress": 0, "count": 0}


def test_tally_computed_from_data(client):
    a = add(client, "a", 100)["id"]
    add(client, "b", 200)
    c = add(client, "c", 300)["id"]
    set_status(client, a, "solved")
    set_status(client, c, "solved")
    tally = client.get("/api/challenges").json()["tally"]
    assert tally == {"earned": 400, "total": 600, "solved": 2, "in_progress": 0, "count": 3}

    # Editing points changes the tally immediately — nothing is cached.
    client.patch(f"/api/challenges/{c}", json={"points": 50})
    tally = client.get("/api/challenges").json()["tally"]
    assert tally["earned"] == 150 and tally["total"] == 350


def test_tally_not_persisted(client, tmp_path):
    cid = add(client)["id"]
    set_status(client, cid, "solved")
    client.post("/api/session/save")
    data = json.loads((tmp_path / "comp.json").read_text())
    assert "tally" not in data
    assert data["challenges"][0]["status"] == "solved"
