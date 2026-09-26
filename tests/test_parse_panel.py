# Sarissa — Phase 7 Parse tab (Treska integration). Sarissa-side HTML/JS only; Treska is not mocked.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sarissa.main import create_app

SRC = Path(__file__).resolve().parent.parent / "src" / "sarissa"
SPEC_OFFLINE = "Treska not running on :7332 — start it with python -m treska"


@pytest.fixture
def html(tmp_path):
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        r = c.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    return r.text


def parse_js(page):
    """The Parse script block: from its marker to the Boot marker."""
    start = page.index("/* ---------- Parse (Treska) ---------- */")
    return page[start:page.index("/* ---------- Boot ---------- */", start)]


def parse_view(page):
    return re.search(r'<main id="parseView".*?</main>', page, re.S).group(0)


def test_tabs_render(html):
    assert 'id="tabCockpit"' in html and 'id="tabParse"' in html
    assert '<main id="cockpitView"' in html
    assert re.search(r'<main id="parseView"[^>]*\bhidden\b', html), "Parse view starts hidden"
    assert re.search(r'<button[^>]*id="tabParse"[^>]*>Parse</button>', html)
    # #cockpitView sets display: grid, so a plain main[hidden] rule would lose on specificity.
    assert "#cockpitView[hidden], #parseView[hidden] { display: none; }" in html


def test_parse_view_layout(html):
    view = parse_view(html)
    assert 'id="parseDrop"' in view
    assert re.search(r'<input id="parseFile" type="file" accept="\.zip,application/zip">', view)
    for box in ("pFlaggedOut", "pSqliteOut", "pInventoryOut", "treskaBanner", "parseError"):
        assert f'id="{box}"' in view
    inventory = re.search(r"<details id=\"pInventoryWrap\">.*?</details>", view, re.S).group(0)
    assert 'id="pInventoryOut"' in inventory
    assert "<details id=\"pInventoryWrap\" open" not in view


def test_treska_url_single_constant(html):
    assert html.count("http://localhost:7332") == 1
    js = parse_js(html)
    assert 'const TRESKA = "http://localhost:7332";' in js
    assert 'fetch(TRESKA + "/api/parse", { method: "POST", body })' in js
    assert 'body.append("file", file, file.name)' in js and "new FormData()" in js


def test_offline_banner_text(html):
    assert SPEC_OFFLINE in parse_js(html)


def test_export_json_client_side(html):
    assert re.search(r'<button[^>]*id="parseExport"[^>]*>Export JSON</button>', html)
    js = parse_js(html)
    assert "new Blob(" in js and "URL.createObjectURL" in js and "download:" in js


@pytest.mark.parametrize("banned", ["innerHTML", "outerHTML", "insertAdjacentHTML", "alert(", "confirm(", "prompt(", "green"])
def test_no_banned_constructs(html, banned):
    assert banned.lower() not in html.lower()


def test_no_treska_red_in_parse(html):
    assert html.lower().count("#e74c3c") == 1  # the pre-existing --warn token (timer urgency only)
    assert "--warn" not in parse_js(html)
    assert "--warn" not in parse_view(html)
    parse_css = html[html.index("/* Parse (Treska on :7332)"):html.index("#toast {")]
    assert "var(--warn)" not in parse_css and "var(--crimson" in parse_css


def test_no_sarissa_parse_route(tmp_path):
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        assert c.post("/api/parse", files={"file": ("a.zip", b"PK", "application/zip")}).status_code in (404, 405)
        paths = {getattr(r, "path", "") for r in c.app.routes}
    assert not any("parse" in p or "treska" in p for p in paths)


def test_no_treska_in_python():
    for py in SRC.rglob("*.py"):
        assert "treska" not in py.read_text(encoding="utf-8").lower(), py


def test_cockpit_keeps_all_four_tools(html):
    cockpit = re.search(r'<main id="cockpitView".*?</main>', html, re.S).group(0)
    for title in ("Hash calculator", "Timestamp converter", "File type inspector", "String extractor"):
        assert f"<h2>{title}</h2>" in cockpit
