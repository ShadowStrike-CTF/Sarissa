# Sarissa — Phase 15 post-competition review (GET /api/review, read-only).
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import pytest
from fastapi.testclient import TestClient

from sarissa.api import challenges
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


@pytest.fixture
def clock(monkeypatch):
    """Server time for the timer routes and the review; set clock.now to move it."""
    class Clock:
        now = "2026-10-25T10:00:00Z"

    monkeypatch.setattr(challenges, "utc_now", lambda: Clock.now)
    return Clock


def add(client, name="chal", category="", points=0):
    r = client.post("/api/challenges", json={"name": name, "category": category, "points": points})
    assert r.status_code == 201
    return r.json()["id"]


def timer(client, cid, action):
    assert client.post(f"/api/challenges/{cid}/timer/{action}").status_code == 200


def spend(client, clock, cid, start, stop):
    """Run the challenge timer from `start` to `stop` (ISO times)."""
    clock.now = start
    timer(client, cid, "start")
    clock.now = stop
    timer(client, cid, "stop")


def solve(client, cid):
    assert client.patch(f"/api/challenges/{cid}/score", json={"solved": True}).status_code == 200


def review(client):
    r = client.get("/api/review")
    assert r.status_code == 200
    return r.json()


def test_review_empty_session(client, clock):
    data = review(client)
    assert data["generated_utc"] == "2026-10-25T10:00:00Z"
    assert data["totals"] == {
        "challenges": 0, "solved": 0, "time_seconds": 0, "points_earned": 0,
        "points_available": 0, "points_per_hour": None, "unsolved_time_seconds": 0,
    }
    assert data["by_category"] == []
    assert data["by_challenge"] == []


def test_review_category_rollup(client, clock):
    a = add(client, "disk", "Forensics", 100)
    b = add(client, "pcap", "Forensics", 200)
    c = add(client, "rsa", "Crypto", 50)
    d = add(client, "warmup")  # no category, no points
    spend(client, clock, a, "2026-10-25T10:00:00Z", "2026-10-25T10:30:00Z")  # 1800 s
    spend(client, clock, b, "2026-10-25T10:30:00Z", "2026-10-25T11:00:00Z")  # 1800 s
    spend(client, clock, c, "2026-10-25T11:00:00Z", "2026-10-25T11:10:00Z")  # 600 s
    spend(client, clock, d, "2026-10-25T11:10:00Z", "2026-10-25T11:11:00Z")  # 60 s
    solve(client, a)
    data = review(client)
    assert data["by_category"] == [
        {"category": "Forensics", "challenges": 2, "solved": 1, "time_seconds": 3600,
         "points_earned": 100, "points_available": 300, "points_per_hour": 100.0},
        {"category": "Crypto", "challenges": 1, "solved": 0, "time_seconds": 600,
         "points_earned": 0, "points_available": 50, "points_per_hour": 0.0},
        {"category": "Uncategorised", "challenges": 1, "solved": 0, "time_seconds": 60,
         "points_earned": 0, "points_available": 0, "points_per_hour": 0.0},
    ]
    t = data["totals"]
    assert (t["challenges"], t["solved"], t["time_seconds"]) == (4, 1, 4260)
    assert (t["points_earned"], t["points_available"]) == (100, 350)
    assert t["points_per_hour"] == round(100 / (4260 / 3600), 2)


def test_review_sorted_by_time_desc(client, clock):
    ids = {name: add(client, name) for name in ("b-short", "zeta", "alpha", "idle")}
    spend(client, clock, ids["b-short"], "2026-10-25T10:00:00Z", "2026-10-25T10:00:10Z")
    spend(client, clock, ids["zeta"], "2026-10-25T10:00:10Z", "2026-10-25T10:05:10Z")
    spend(client, clock, ids["alpha"], "2026-10-25T10:05:10Z", "2026-10-25T10:10:10Z")
    rows = review(client)["by_challenge"]
    # Time desc, then name: alpha and zeta tie on 300 s.
    assert [(r["name"], r["time_seconds"]) for r in rows] == [
        ("alpha", 300), ("zeta", 300), ("b-short", 10), ("idle", 0),
    ]
    assert set(rows[0]) == {"id", "name", "category", "status", "time_seconds", "points", "solved", "running"}
    assert rows[0]["category"] == "Uncategorised"


def test_review_running_timer_counts_live(client, clock):
    cid = add(client, "live", "OSINT", 30)
    spend(client, clock, cid, "2026-10-25T10:00:00Z", "2026-10-25T10:01:00Z")  # 60 s banked
    clock.now = "2026-10-25T10:02:00Z"
    timer(client, cid, "start")
    clock.now = "2026-10-25T10:02:45Z"
    row = review(client)["by_challenge"][0]
    assert (row["time_seconds"], row["running"]) == (105, True)
    # The review never banks or stops the timer.
    state = client.get(f"/api/challenges/{cid}/timer").json()
    assert state["challenge_time_seconds"] == 60
    assert state["challenge_timer_started_at"] == "2026-10-25T10:02:00Z"


def test_review_does_not_mutate_session(client, clock, tmp_path):
    cid = add(client, "disk", "Forensics", 100)
    clock.now = "2026-10-25T10:00:00Z"
    timer(client, cid, "start")  # running: start saves the session
    path = tmp_path / "comp.json"
    before = path.read_bytes()
    listed = client.get("/api/challenges").json()["challenges"]
    clock.now = "2026-10-25T10:20:00Z"
    review(client)
    assert path.read_bytes() == before
    assert client.get("/api/challenges").json()["challenges"] == listed


def test_review_unsolved_time_sink(client, clock):
    a = add(client, "solved one", "Forensics", 100)
    b = add(client, "stuck", "Forensics", 300)
    c = add(client, "started", "Crypto", 50)
    spend(client, clock, a, "2026-10-25T10:00:00Z", "2026-10-25T10:10:00Z")  # 600 s, solved
    spend(client, clock, b, "2026-10-25T10:10:00Z", "2026-10-25T11:10:00Z")  # 3600 s, unsolved
    spend(client, clock, c, "2026-10-25T11:10:00Z", "2026-10-25T11:15:00Z")  # 300 s, in progress
    solve(client, a)
    assert client.post(f"/api/challenges/{c}/status", json={"status": "in_progress"}).status_code == 200
    data = review(client)
    assert data["totals"]["unsolved_time_seconds"] == 3900
    rows = {r["name"]: r for r in data["by_challenge"]}
    assert rows["solved one"]["solved"] is True and rows["solved one"]["status"] == "solved"
    assert rows["started"]["solved"] is False and rows["started"]["status"] == "in_progress"


def test_review_409_no_session(bare_client):
    assert bare_client.get("/api/review").status_code == 409


def test_export_schema_unchanged_1_3(client, clock):
    cid = add(client, "disk", "Forensics", 100)
    spend(client, clock, cid, "2026-10-25T10:00:00Z", "2026-10-25T10:00:30Z")
    before = client.get("/api/export").json()
    review(client)
    after = client.get("/api/export").json()
    assert after["schema_version"] == "1.3"
    assert after["challenges"] == before["challenges"]
    stored = set(after["challenges"][0])
    assert not stored & {"running", "time_seconds", "points_per_hour", "review"}


def test_review_ui_static(tmp_path):
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        page = c.get("/").text
    js = page[page.index("<script>"):page.index("</script>")]
    assert 'id="reviewPanel"' in page and 'id="reviewBtn"' in page
    shortcuts = js[js.index("const SHORTCUTS = ["):js.index("];", js.index("const SHORTCUTS = ["))]
    assert '["r",' in shortcuts
    keymap = js[js.index("const KEYMAP = {"):js.index("\n};\n", js.index("const KEYMAP = {"))]
    assert "r: toggleReview" in keymap
    assert 'api("/api/review")' in js
    escape = js[js.index('if (ev.key === "Escape") {'):js.index("return;", js.index('if (ev.key === "Escape") {'))]
    assert '$("reviewPanel").hidden = true' in escape
    for banned in ("innerHTML", "localStorage", "sessionStorage", "alert(", "confirm(", "prompt("):
        assert banned not in js
