# Sarissa — Phase 9 session export (GET /api/export, schema v1.0).
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

from datetime import datetime, timezone

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


def test_export_active_session(client):
    """Export with an active session returns 200, valid JSON and an attachment filename."""
    resp = client.get("/api/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert resp.headers["content-disposition"] == f'attachment; filename="sarissa-comp-{date}.json"'
    data = resp.json()
    assert data["schema_version"] == "1.0"
    assert data["tool"] == "Sarissa"


def test_export_no_session(bare_client):
    """No active session → 409, the app-wide NoActiveSession convention."""
    assert bare_client.get("/api/export").status_code == 409


def test_export_schema_fields(client):
    """Only fields the session actually holds are exported — nothing fabricated."""
    chal = client.post("/api/challenges", json={"name": "disk image", "points": 200}).json()
    data = client.get("/api/export").json()
    assert set(data) == {"schema_version", "tool", "session", "challenges"}
    assert set(data["session"]) == {"name", "created_at", "updated_at", "exported_at", "timer"}
    assert data["session"]["name"] == "comp"
    assert set(data["session"]["timer"]) == {"mode", "duration_seconds", "started_at"}
    assert [c["id"] for c in data["challenges"]] == [chal["id"]]
    assert data["challenges"][0]["name"] == "disk image"
    assert "results" not in data
