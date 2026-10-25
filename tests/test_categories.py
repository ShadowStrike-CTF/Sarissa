# Sarissa — Phase 12 challenge categories (PATCH category, GET /api/session/categories, filter bar).
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


def add(client, name="chal", category=""):
    r = client.post("/api/challenges", json={"name": name, "category": category})
    assert r.status_code == 201
    return r.json()


def set_category(client, cid, category):
    return client.patch(f"/api/challenges/{cid}/category", json={"category": category})


def saved_challenge(client, tmp_path, cid):
    """Force a save and read the challenge back from the session file on disk."""
    assert client.post("/api/session/save").status_code == 200
    data = json.loads((tmp_path / "comp.json").read_text(encoding="utf-8"))
    return next(c for c in data["challenges"] if c["id"] == cid)


def test_patch_challenge_category(client, tmp_path):
    cid = add(client)["id"]
    r = set_category(client, cid, "Forensics")
    assert r.status_code == 200
    assert r.json()["category"] == "Forensics" and r.json()["status"] == "unsolved"
    assert saved_challenge(client, tmp_path, cid)["category"] == "Forensics"
    # Content is not validated or normalised: hostile-looking text is stored exactly as sent.
    odd = " <b>x</b> & ' \" "
    assert set_category(client, cid, odd).json()["category"] == odd
    assert set_category(client, "nope", "Crypto").status_code == 404
    for body in ({"category": 1}, {"category": None}, {}, {"category": "x" * 65},
                 {"category": "Crypto", "status": "solved"}):
        assert client.patch(f"/api/challenges/{cid}/category", json=body).status_code == 422, body
    assert set_category(client, cid, "x" * 64).status_code == 200


def test_patch_challenge_category_empty_string(client, tmp_path):
    cid = add(client, category="Crypto")["id"]
    r = set_category(client, cid, "")
    assert r.status_code == 200 and r.json()["category"] == ""
    assert saved_challenge(client, tmp_path, cid)["category"] == ""


def test_get_session_categories_returns_sorted_unique(client):
    add(client, "a", "OSINT")
    add(client, "b", "Crypto")
    add(client, "c", "Forensics")
    add(client, "d", "Crypto")
    assert client.get("/api/session/categories").json() == ["Crypto", "Forensics", "OSINT"]
    # Server returns challenges in creation order regardless (the filter is frontend-only).
    names = [c["name"] for c in client.get("/api/challenges").json()["challenges"]]
    assert names == ["a", "b", "c", "d"]


def test_get_session_categories_excludes_empty(client):
    add(client, "a", "Crypto")
    cid = add(client, "b", "OSINT")["id"]
    add(client, "c")
    set_category(client, cid, "")
    assert client.get("/api/session/categories").json() == ["Crypto"]


def test_get_session_categories_empty_session(client):
    r = client.get("/api/session/categories")
    assert r.status_code == 200 and r.json() == []
    add(client, "uncategorised")
    assert client.get("/api/session/categories").json() == []


def test_export_category_field(client):
    """No category-specific schema bump: challenges have carried category since v1.0."""
    cid = add(client, "disk image")["id"]
    set_category(client, cid, "Forensics")
    data = client.get("/api/export").json()
    assert data["schema_version"] == "1.3"
    assert data["challenges"][0]["category"] == "Forensics"


def test_category_409_no_session(bare_client):
    assert bare_client.get("/api/session/categories").status_code == 409
    assert bare_client.patch("/api/challenges/x/category", json={"category": "a"}).status_code == 409


def test_cockpit_category_ui(bare_client):
    page = bare_client.get("/").text
    cockpit = page[page.index('<main id="cockpitView"'):page.index("</main>")]
    assert 'id="catFilter"' in cockpit
    assert "/api/session/categories" in page and "/category`" in page
    assert "innerHTML" not in page
