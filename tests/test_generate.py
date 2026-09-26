# Sarissa — Phase 8 Generate tab (Poligon proxy). Poligon is mocked at the httpx transport layer.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import sarissa.main
from sarissa.main import POLIGON_PORT, create_app

SRC = Path(__file__).resolve().parent.parent / "src" / "sarissa"
SCENARIO = "6f1c1f4e-9a7e-4a53-8d0b-3c2b1e0f9a11"
ZIP = b"PK\x05\x06" + b"\x00" * 18  # empty zip archive
VALID = {"template": "android", "seed": 42, "difficulty": 2}


@pytest.fixture
def client(tmp_path):
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
        return httpx.Response(200, json={"scenario_id": SCENARIO, "template": "android", "difficulty": 2,
                                         "download_url": f"/api/download/{SCENARIO}"})
    if request.method == "GET" and request.url.path == f"/api/download/{SCENARIO}":
        return httpx.Response(200, content=ZIP, headers={"content-type": "application/zip"})
    return httpx.Response(404)


def raising(exc):
    def handler(request):
        raise exc("boom", request=request)
    return handler


def test_generate_proxies_zip(client, poligon):
    seen = poligon(happy)
    r = client.post("/api/generate", json=VALID)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == 'attachment; filename="android_42_d2.zip"'
    assert r.content == ZIP
    assert [(q.method, q.url.path) for q in seen] == [("POST", "/api/generate"), ("GET", f"/api/download/{SCENARIO}")]
    assert json.loads(seen[0].content) == VALID
    assert all(q.url.host == "127.0.0.1" and q.url.port == POLIGON_PORT for q in seen)


def test_generate_poligon_offline(client, poligon):
    poligon(raising(httpx.ConnectError))
    r = client.post("/api/generate", json=VALID)
    assert r.status_code == 503
    assert r.json()["detail"] == "Poligon offline"


def test_generate_poligon_timeout(client, poligon):
    poligon(raising(httpx.ReadTimeout))
    assert client.post("/api/generate", json=VALID).status_code == 504


def test_generate_poligon_error(client, poligon):
    poligon(lambda request: httpx.Response(400, json={"detail": "bad"}))
    assert client.post("/api/generate", json=VALID).status_code == 502


def test_generate_download_error(client, poligon):
    def handler(request):
        return happy(request) if request.method == "POST" else httpx.Response(404, json={"detail": "Unknown scenario"})
    poligon(handler)
    assert client.post("/api/generate", json=VALID).status_code == 502


def test_generate_bad_scenario_id(client, poligon):
    seen = poligon(lambda request: httpx.Response(200, json={"scenario_id": "../../etc"}))
    assert client.post("/api/generate", json=VALID).status_code == 502
    assert len(seen) == 1  # never followed to a download


@pytest.mark.parametrize("template", ["windows", "", None, 1])
def test_invalid_template(client, poligon, template):
    seen = poligon(happy)
    assert client.post("/api/generate", json={**VALID, "template": template}).status_code == 422
    assert not seen


@pytest.mark.parametrize("difficulty", [0, 4, "2", True, None])
def test_invalid_difficulty(client, poligon, difficulty):
    seen = poligon(happy)
    assert client.post("/api/generate", json={**VALID, "difficulty": difficulty}).status_code == 422
    assert not seen


@pytest.mark.parametrize("seed", ["42", True, 4.0, None])
def test_invalid_seed(client, poligon, seed):
    seen = poligon(happy)
    assert client.post("/api/generate", json={**VALID, "seed": seed}).status_code == 422
    assert not seen


def test_generate_rejects_non_json_body(client, poligon):
    # A cross-site form/text POST needs no CORS preflight — it must never reach Poligon.
    seen = poligon(happy)
    r = client.post("/api/generate", content=json.dumps(VALID), headers={"Content-Type": "text/plain"})
    assert r.status_code == 422
    assert not seen


def test_poligon_health_online(client, poligon):
    poligon(lambda request: httpx.Response(200, json={"status": "ok", "port": 7333}))
    r = client.get("/api/poligon/health")
    assert r.status_code == 200
    assert r.json() == {"status": "online", "poligon_status": 200, "port": POLIGON_PORT}


def test_poligon_health_error(client, poligon):
    poligon(lambda request: httpx.Response(500))
    assert client.get("/api/poligon/health").json() == {"status": "online", "poligon_status": 500, "port": POLIGON_PORT}


def test_poligon_health_offline(client, poligon):
    poligon(raising(httpx.ConnectError))
    r = client.get("/api/poligon/health")
    assert r.status_code == 200
    assert r.json() == {"status": "offline", "port": POLIGON_PORT}


def test_sarissa_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_poligon_port_single_constant():
    assert POLIGON_PORT == 7333
    hits = [(py.name, n) for py in SRC.rglob("*.py")
            for n, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1) if "7333" in line]
    assert hits == [("main.py", hits[0][1])], hits


# --- Frontend (Sarissa-side HTML/JS only) -----------------------------------

@pytest.fixture
def html(client):
    r = client.get("/")
    assert r.status_code == 200
    return r.text


def generate_js(page):
    start = page.index("/* ---------- Generate (Poligon) ---------- */")
    return page[start:page.index("/* ---------- Boot ---------- */", start)]


def generate_view(page):
    return re.search(r'<main id="generateView".*?</main>', page, re.S).group(0)


def test_generate_tab_renders(html):
    assert re.search(r'<button[^>]*id="tabGenerate"[^>]*>Generate</button>', html)
    assert html.index('id="tabCockpit"') < html.index('id="tabParse"') < html.index('id="tabGenerate"')
    assert re.search(r'<main id="generateView"[^>]*\bhidden\b', html), "Generate view starts hidden"
    assert "#generateView[hidden] { display: none; }" in html


def test_generate_form(html):
    view = generate_view(html)
    template = re.search(r'<select id="genTemplate">(.*?)</select>', view, re.S).group(1)
    assert re.findall(r'value="(\w+)"', template) == ["android", "filesystem", "evidence"]
    assert re.search(r'<input id="genSeed"[^>]*type="number"[^>]*value="42"', view)
    difficulty = re.search(r'<select id="genDifficulty">(.*?)</select>', view, re.S).group(1)
    assert re.findall(r'value="(\d)"', difficulty) == ["1", "2", "3"]
    for box in ("poligonBanner", "genSubmit", "genError", "genLast", "genAgain"):
        assert f'id="{box}"' in view


def test_generate_js_uses_proxy_only(html):
    js = generate_js(html)
    assert 'fetch("/api/generate", {' in js and 'method: "POST"' in js
    assert 'api("/api/poligon/health")' in js
    assert "7333" not in html  # port reaches the page only via /api/poligon/health
    assert "localhost:7333" not in html and "127.0.0.1" not in html


def test_last_generated_is_memory_only(html):
    js = generate_js(html)
    assert "let lastGenerated = null;" in js
    assert "Last generated: ${template} · seed ${seed} · d${difficulty}" in js
    assert '$("genLast").textContent' in js
    assert "URL.createObjectURL(blob)" in js and '$("genAgain").href = lastGenerated.url' in js
    assert "${template}_${seed}_d${difficulty}.zip" in js
    for banned in ("localStorage", "sessionStorage", "indexedDB"):
        assert banned not in html


@pytest.mark.parametrize("banned", [r"\btransition(-\w+)?\s*:", r"\banimation(-\w+)?\s*:", r"@keyframes", r"\.animate\("])
def test_no_motion(html, banned):
    assert not re.search(banned, html, re.I)


def test_generate_ui_no_warn_red(html):
    assert "--warn" not in generate_js(html) and "--warn" not in generate_view(html)
