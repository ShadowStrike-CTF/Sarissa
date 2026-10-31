# Sarissa — v1.8.1: all six Poligon templates in Generate + short-run pts/h display.
# Poligon is mocked at the httpx transport layer, as in tests/test_generate.py.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import json
import re
from pathlib import Path
from typing import get_args

import httpx
import pytest
from fastapi.testclient import TestClient

import sarissa.main
from sarissa.api import challenges
from sarissa.main import GenerateRequest, create_app

SRC = Path(__file__).resolve().parent.parent / "src" / "sarissa"
SCENARIO = "6f1c1f4e-9a7e-4a53-8d0b-3c2b1e0f9a11"
ZIP = b"PK\x05\x06" + b"\x00" * 18  # empty zip archive
POLIGON_1_3_2_TEMPLATES = ("android", "filesystem", "evidence", "browser", "evtx", "ios")


@pytest.fixture
def bare_client(tmp_path):
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        yield c


@pytest.fixture
def poligon(monkeypatch):
    """Route Sarissa's Poligon calls to `handler`; records every request it sees."""
    seen = []

    def install(handler):
        def recording(request):
            seen.append(request)
            return handler(request)

        real = httpx.AsyncClient
        monkeypatch.setattr(sarissa.main, "poligon_client",
                            lambda timeout: real(base_url=sarissa.main.POLIGON_URL, transport=httpx.MockTransport(recording)))
        return seen

    return install


def happy(request):
    if request.method == "POST" and request.url.path == "/api/generate":
        return httpx.Response(200, json={"scenario_id": SCENARIO, "download_url": f"/api/download/{SCENARIO}"})
    if request.method == "GET" and request.url.path == f"/api/download/{SCENARIO}":
        return httpx.Response(200, content=ZIP, headers={"content-type": "application/zip"})
    return httpx.Response(404)


def test_allowlist_matches_poligon_1_3_2():
    assert get_args(GenerateRequest.model_fields["template"].annotation) == POLIGON_1_3_2_TEMPLATES


@pytest.mark.parametrize("template", ["browser", "evtx", "ios"])
def test_generate_new_templates_proxied(bare_client, poligon, template):
    seen = poligon(happy)
    r = bare_client.post("/api/generate", json={"template": template, "seed": 42, "difficulty": 2})
    assert r.status_code == 200
    assert r.content == ZIP
    assert r.headers["content-disposition"] == f'attachment; filename="{template}_42_d2.zip"'
    assert len(seen) == 2
    assert json.loads(seen[0].content)["template"] == template


def test_unknown_template_still_rejected(bare_client, poligon):
    seen = poligon(happy)
    for template in ("Browser", "chrome", "evtx ", "iOS", "windows"):
        r = bare_client.post("/api/generate", json={"template": template, "seed": 42, "difficulty": 2})
        assert r.status_code == 422, template
    assert not seen


def test_pph_dash_rule_static():
    html = (SRC / "static" / "index.html").read_text(encoding="utf-8")
    assert "const PPH_MIN_SECONDS = 60;" in html
    assert re.search(r"const fmtRate = \(r, secs\) => \(r === null \|\| secs < PPH_MIN_SECONDS \? DASH", html)
    # Both places: totals and per category. No call without the time check.
    assert "fmtRate(t.points_per_hour, t.time_seconds)" in html
    assert "fmtRate(g.points_per_hour, g.time_seconds)" in html
    assert len(re.findall(r"fmtRate\(", html)) == 2


def test_review_api_still_numeric_short_run(bare_client, monkeypatch):
    class Clock:
        now = "2026-10-25T10:00:00Z"

    monkeypatch.setattr(challenges, "utc_now", lambda: Clock.now)
    assert bare_client.post("/api/session", json={"name": "comp"}).status_code == 201
    cid = bare_client.post("/api/challenges", json={"name": "quick", "category": "", "points": 100}).json()["id"]
    assert bare_client.post(f"/api/challenges/{cid}/timer/start").status_code == 200
    Clock.now = "2026-10-25T10:00:16Z"
    assert bare_client.post(f"/api/challenges/{cid}/timer/stop").status_code == 200
    assert bare_client.patch(f"/api/challenges/{cid}/score", json={"solved": True}).status_code == 200
    data = bare_client.get("/api/review").json()
    assert data["totals"]["time_seconds"] == 16
    assert data["totals"]["points_per_hour"] == 22500.0
    assert data["by_category"][0]["points_per_hour"] == 22500.0
