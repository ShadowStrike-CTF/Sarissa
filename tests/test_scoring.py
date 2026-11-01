# Sarissa — Phase 11 challenge scoring (PATCH score, GET /api/session/score, cockpit UI).
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import json

import pytest
from fastapi.testclient import TestClient

from sarissa.main import create_app


@pytest.fixture
def bare_client(tmp_path):
    """App as launched: no session open until the picker creates or restores one."""
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        yield c


@pytest.fixture
def client(bare_client):
    assert bare_client.post("/api/session", json={"name": "comp"}).status_code == 201
    return bare_client


def add(client, name="chal", points=0):
    r = client.post("/api/challenges", json={"name": name, "points": points})
    assert r.status_code == 201
    return r.json()


def score(client, cid, **body):
    return client.patch(f"/api/challenges/{cid}/score", json=body)


def saved_challenge(client, tmp_path, cid):
    """Force a save and read the challenge back from the session file on disk."""
    assert client.post("/api/session/save").status_code == 200
    data = json.loads((tmp_path / "comp.json").read_text(encoding="utf-8"))
    return next(c for c in data["challenges"] if c["id"] == cid)


def test_patch_challenge_score_point_value(client, tmp_path):
    cid = add(client)["id"]
    r = score(client, cid, point_value=250)
    assert r.status_code == 200
    assert r.json()["points"] == 250
    stored = saved_challenge(client, tmp_path, cid)
    assert stored["points"] == 250
    # point_value maps onto the existing field — no second copy is stored.
    assert "point_value" not in stored and "solved" not in stored


def test_patch_challenge_score_solved(client, tmp_path):
    cid = add(client, points=100)["id"]
    r = score(client, cid, solved=True)
    assert r.status_code == 200
    assert r.json()["status"] == "solved" and r.json()["solved_at"]
    stored = saved_challenge(client, tmp_path, cid)
    assert stored["status"] == "solved" and stored["solved_at"]
    # Solving again is a no-op: solved_at is not rewritten.
    assert score(client, cid, solved=True).json()["solved_at"] == stored["solved_at"]


def test_patch_challenge_score_partial(client):
    cid = add(client, points=100)["id"]
    client.post(f"/api/challenges/{cid}/status", json={"status": "in_progress"})
    r = score(client, cid, point_value=300)
    assert r.status_code == 200
    assert r.json()["points"] == 300 and r.json()["status"] == "in_progress"
    # Empty body changes nothing.
    r = score(client, cid)
    assert r.json()["points"] == 300 and r.json()["status"] == "in_progress"


def test_get_session_score_totals(client):
    a = add(client, "a", 100)["id"]
    add(client, "b", 200)
    c = add(client, "c", 50)["id"]
    score(client, a, solved=True)
    score(client, c, solved=True)
    assert client.get("/api/session/score").json() == {
        "total_points": 350,
        "secured_points": 150,
        "remaining_points": 200,
        "solved_count": 2,
        "total_challenges": 3,
    }
    # Totals follow the data immediately — nothing is cached.
    score(client, a, point_value=400)
    s = client.get("/api/session/score").json()
    assert s["total_points"] == 650 and s["secured_points"] == 450 and s["remaining_points"] == 200


def test_get_session_score_excludes_zero_value(client):
    add(client, "scored", 100)
    unset = add(client, "unset", 0)["id"]
    score(client, unset, solved=True)
    s = client.get("/api/session/score").json()
    # The unset challenge counts as a challenge (and as solved) but adds no points.
    assert s["total_points"] == 100 and s["secured_points"] == 0 and s["remaining_points"] == 100
    assert s["solved_count"] == 1 and s["total_challenges"] == 2


def test_export_scoring_fields(client):
    """No scoring-specific schema bump: scoring data travels in the stored points/status fields."""
    cid = add(client, "disk image", 200)["id"]
    score(client, cid, solved=True)
    data = client.get("/api/export").json()
    assert data["schema_version"] == "1.3"
    chal = data["challenges"][0]
    assert chal["points"] == 200 and chal["status"] == "solved"
    assert "point_value" not in chal and "solved" not in chal


def test_score_409_no_session(bare_client):
    assert bare_client.get("/api/session/score").status_code == 409
    assert bare_client.patch("/api/challenges/x/score", json={"point_value": 1}).status_code == 409


def test_patch_score_cannot_unsolve(client):
    cid = add(client, points=100)["id"]
    score(client, cid, solved=True)
    # solved: false never moves status backwards — and the whole body is rejected, points included.
    r = score(client, cid, point_value=999, solved=False)
    assert r.status_code == 409
    chal = client.get("/api/challenges").json()["challenges"][0]
    assert chal["status"] == "solved" and chal["points"] == 100
    # On an unsolved challenge, solved: false is a plain no-op.
    other = add(client, "other")["id"]
    r = score(client, other, solved=False, point_value=5)
    assert r.status_code == 200 and r.json()["status"] == "unsolved" and r.json()["points"] == 5


def test_patch_score_validation(client):
    cid = add(client, points=100)["id"]
    for body in (
        {"point_value": True},
        {"point_value": "100"},
        {"point_value": 1.0},
        {"point_value": -1},
        {"point_value": 10000},
        {"solved": 1},
        {"solved": "yes"},
        {"status": "solved"},  # extra keys forbidden: status can't sneak in here either
    ):
        assert score(client, cid, **body).status_code == 422, body
    assert score(client, cid, point_value=9999).status_code == 200
    score(client, cid, point_value=100)
    assert score(client, "nope", point_value=1).status_code == 404
    chal = client.get("/api/challenges").json()["challenges"][0]
    assert chal["points"] == 100 and chal["status"] == "unsolved"


def test_cockpit_scoring_ui(bare_client):
    page = bare_client.get("/").text
    header = page[page.index('<div class="session-bar">'):page.index("</header>")]
    assert 'id="scorePanel"' in header
    assert 'id="chalSort"' in page and "By points (high → low)" in page
    assert "/api/session/score" in page and "/score`" in page


def test_score_counts_one_point_challenge(client):
    # Mutation sweep (J01): points == 1 is a real value, only 0 means unset.
    cid = add(client, points=1)["id"]
    assert score(client, cid, solved=True).status_code == 200
    body = client.get("/api/session/score").json()
    assert (body["total_points"], body["secured_points"], body["remaining_points"]) == (1, 1, 0)
