# Sarissa — F14 manifest export (GET /api/manifest, v1.11.0).
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import hashlib
import json
import tomllib
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import sarissa
from sarissa.api import challenges
from sarissa.main import MANIFEST_KEYS, create_app

TOP_KEYS = {"sarissa_version", "exported_at", "challenge_count", "manifest_hash", "challenges"}
CHAL_KEYS = {"id", "name", "category", "points", "solved", "solved_at"}
EMPTY_HASH = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"  # design doc §6


@pytest.fixture
def bare_client(tmp_path):
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        yield c


@pytest.fixture
def client(bare_client):
    assert bare_client.post("/api/session", json={"name": "comp"}).status_code == 201
    return bare_client


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        now = "2026-11-07T12:00:00Z"

    monkeypatch.setattr(challenges, "utc_now", lambda: Clock.now)
    return Clock


def add(client, name="chal", category="", points=0, notes=""):
    body = {"name": name, "category": category, "points": points, "notes": notes}
    r = client.post("/api/challenges", json=body)
    assert r.status_code == 201
    return r.json()["id"]


def manifest(client):
    r = client.get("/api/manifest")
    assert r.status_code == 200
    return r.json()


def recipe(items):
    canonical = json.dumps(items, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_manifest_shape(client):
    add(client, "disk image", "Forensics", 100)
    r = client.get("/api/manifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert "content-disposition" not in r.headers
    data = r.json()
    assert set(data) == TOP_KEYS
    assert data["challenge_count"] == 1
    assert set(data["challenges"][0]) == CHAL_KEYS == set(MANIFEST_KEYS)
    assert data["exported_at"].endswith("Z")


def test_manifest_ordering(client):
    add(client, "zeta", "Forensics")
    add(client, "alpha", "Forensics")
    add(client, "no category", "")
    add(client, "lower", "crypto")
    add(client, "upper", "Crypto")
    dup = sorted([add(client, "same", "OSINT"), add(client, "same", "OSINT")])
    rows = manifest(client)["challenges"]
    assert [(c["category"], c["name"]) for c in rows] == [
        ("", "no category"),
        ("Crypto", "upper"),
        ("Forensics", "alpha"),
        ("Forensics", "zeta"),
        ("OSINT", "same"),
        ("OSINT", "same"),
        ("crypto", "lower"),  # case-sensitive: lowercase after uppercase
    ]
    assert [c["id"] for c in rows if c["name"] == "same"] == dup  # id breaks the tie


def test_manifest_hash_reproducible(client, monkeypatch):
    add(client, "b", "Forensics", 100)
    add(client, "a", "Forensics", 0)
    from sarissa.api import session

    monkeypatch.setattr(session, "utc_now", lambda: "2026-11-07T12:00:00Z")
    first = manifest(client)
    monkeypatch.setattr(session, "utc_now", lambda: "2026-11-07T13:00:00Z")
    second = manifest(client)
    assert first["exported_at"] != second["exported_at"]
    assert first["manifest_hash"] == second["manifest_hash"] == recipe(first["challenges"])


def test_manifest_hash_worked_example():
    """The §3/§6 example list from the design doc hashes to the documented value."""
    items = [
        {"id": "a1b2c3d4e5f6", "name": "Disk image", "category": "Forensics", "points": 100,
         "solved": True, "solved_at": "2026-11-07T12:34:56Z"},
        {"id": "0f9e8d7c6b5a", "name": "Ransom note", "category": "Forensics", "points": 0,
         "solved": False, "solved_at": None},
    ]
    from sarissa.main import manifest_hash

    assert manifest_hash(items) == "15567ddbf7d345e3d1190497e7a09606ba52423aa1ee0fa092f484630670e03d"
    assert manifest_hash([]) == EMPTY_HASH


def test_manifest_solved_at(client, clock):
    a = add(client, "solved", "X")
    b = add(client, "started", "X")
    add(client, "untouched", "X")
    clock.now = "2026-11-07T12:34:56Z"
    assert client.patch(f"/api/challenges/{a}/score", json={"solved": True}).status_code == 200
    assert client.post(f"/api/challenges/{b}/status", json={"status": "in_progress"}).status_code == 200
    rows = {c["name"]: c for c in manifest(client)["challenges"]}
    assert rows["solved"]["solved"] is True
    assert rows["solved"]["solved_at"] == "2026-11-07T12:34:56Z"
    datetime.fromisoformat(rows["solved"]["solved_at"])  # parses on Python >= 3.11
    for name in ("started", "untouched"):
        assert rows[name]["solved"] is False
        assert rows[name]["solved_at"] is None


def test_manifest_no_plaintext_flag(client):
    secret = "flag{s3cr3t_n0t_f0r_3xp0rt}"
    add(client, "disk", "Forensics", 100, notes=f"found it: {secret}")
    r = client.get("/api/manifest")
    assert secret not in r.text
    assert all(secret not in v for v in r.headers.values())
    for c in r.json()["challenges"]:
        assert set(c) == CHAL_KEYS
        assert not any("flag" in k or k == "notes" for k in c)


def test_manifest_empty_session(client):
    data = manifest(client)
    assert data["challenge_count"] == 0
    assert data["challenges"] == []
    assert data["manifest_hash"] == EMPTY_HASH


def test_manifest_409_no_session(bare_client):
    assert bare_client.get("/api/manifest").status_code == 409


def test_manifest_read_only(client, clock, tmp_path):
    cid = add(client, "disk", "Forensics", 100)
    clock.now = "2026-11-07T10:00:00Z"
    assert client.post(f"/api/challenges/{cid}/timer/start").status_code == 200  # saves
    path = tmp_path / "comp.json"
    before = path.read_bytes()
    listed = client.get("/api/challenges").json()["challenges"]
    clock.now = "2026-11-07T10:20:00Z"
    manifest(client)
    assert path.read_bytes() == before
    assert client.get("/api/challenges").json()["challenges"] == listed
    state = client.get(f"/api/challenges/{cid}/timer").json()
    assert state["challenge_timer_started_at"] == "2026-11-07T10:00:00Z"


def test_manifest_version(client):
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text("utf-8"))
    assert sarissa.__version__ == pyproject["project"]["version"] == "1.11.0"
    assert manifest(client)["sarissa_version"] == sarissa.__version__


def test_manifest_trusted_host(client):
    assert client.get("/api/manifest", headers={"Host": "evil.example"}).status_code == 400


def test_export_unchanged(client):
    assert client.get("/api/export").json()["schema_version"] == "1.3"
