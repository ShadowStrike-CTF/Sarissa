# Sarissa — manifest export (GET /api/manifest, read-only).
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import hashlib
import json
import re

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


def add(client, name="chal", category="", points=0, notes=""):
    r = client.post(
        "/api/challenges", json={"name": name, "category": category, "points": points, "notes": notes}
    )
    assert r.status_code == 201
    return r.json()["id"]


def manifest(client):
    r = client.get("/api/manifest")
    assert r.status_code == 200
    return r.json()


def expected_hash(items):
    canonical = json.dumps(sorted(items, key=lambda c: c["id"]), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def test_manifest_schema(client):
    add(client, "alpha")
    m = manifest(client)
    assert set(m) == {"challenges", "total", "manifest_hash"}
    assert isinstance(m["challenges"], list)
    assert isinstance(m["total"], int) and not isinstance(m["total"], bool)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", m["manifest_hash"])
    (item,) = m["challenges"]
    assert set(item) == {"id", "name", "status"}
    assert all(isinstance(v, str) for v in item.values())
    assert item["name"] == "alpha"
    assert item["status"] == "unsolved"


def test_manifest_hash_deterministic(client):
    add(client, "alpha")
    add(client, "beta")
    first, second = manifest(client), manifest(client)
    assert first == second
    assert first["manifest_hash"] == expected_hash(first["challenges"])


def test_manifest_hash_sensitive(client):
    cid = add(client, "alpha")
    add(client, "beta")
    before = manifest(client)["manifest_hash"]
    assert client.post(f"/api/challenges/{cid}/status", json={"status": "in_progress"}).status_code == 200
    after_status = manifest(client)
    assert after_status["manifest_hash"] != before
    assert after_status["manifest_hash"] == expected_hash(after_status["challenges"])
    assert client.patch(f"/api/challenges/{cid}", json={"name": "alpha2"}).status_code == 200
    assert manifest(client)["manifest_hash"] != after_status["manifest_hash"]


def test_manifest_empty_session(client):
    assert manifest(client) == {
        "challenges": [],
        "total": 0,
        "manifest_hash": "sha256:" + hashlib.sha256(b"[]").hexdigest(),
    }


def test_manifest_total_matches_len(client):
    for name in ("a", "b", "c"):
        add(client, name)
    m = manifest(client)
    assert m["total"] == len(m["challenges"]) == 3


def test_manifest_sorted_by_id_and_no_extra_fields(client):
    for name in ("one", "two", "three", "four"):
        add(client, name, category="Forensics", points=100, notes="secret note")
    m = manifest(client)
    ids = [c["id"] for c in m["challenges"]]
    assert ids == sorted(ids)
    body = json.dumps(m)
    for leaked in ("secret note", "Forensics", "points", "notes", "flag", "challenge_time_seconds"):
        assert leaked not in body


def test_manifest_409_no_session(bare_client):
    assert bare_client.get("/api/manifest").status_code == 409
