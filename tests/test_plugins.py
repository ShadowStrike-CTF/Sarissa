# Sarissa — v1.9.0 plugin panel slot: loading rules, /api/plugins, /api/panels, Panels tab.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import copy
import logging
import re
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import sarissa.main
from sarissa import plugins
from sarissa.main import create_app

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def dummies(monkeypatch):
    """Put the test-only dummy plugins (and their entry points) on sys.path."""
    monkeypatch.syspath_prepend(str(FIXTURES))
    yield
    for mod in [m for m in sys.modules if m == "dummy_panels" or m.startswith("dummy_panels.")]:
        del sys.modules[mod]


def make_client(tmp_path, allow=(), name="comp"):
    client = TestClient(create_app(sessions_dir=tmp_path, allow=allow))
    if name:
        assert client.post("/api/session", json={"name": name}).status_code == 201
    return client


def add(client, name="chal", points=0):
    r = client.post("/api/challenges", json={"name": name, "points": points})
    assert r.status_code == 201
    return r.json()["id"]


def loaded_names(client):
    r = client.get("/api/plugins")
    assert r.status_code == 200
    return [p["name"] for p in r.json()]


def panel_names(client):
    r = client.get("/api/panels")
    assert r.status_code == 200
    return [p["name"] for p in r.json()]


# --- No plugins: behaviour unchanged -----------------------------------------

def test_no_plugins_by_default(tmp_path, dummies):
    # Dummies are installed, but nothing is allowlisted: nothing loads, nothing is imported.
    with make_client(tmp_path) as c:
        assert c.get("/api/plugins").json() == []
        assert c.get("/api/panels").json() == []
    assert "dummy_panels" not in sys.modules


# --- LR-1 allowlist ------------------------------------------------------------

def test_panel_loads_when_allowlisted(tmp_path, dummies):
    with make_client(tmp_path, allow=["dummy"]) as c:
        add(c, "one")
        add(c, "two")
        assert c.get("/api/plugins").json() == [{"name": "dummy", "version": "0.0.0", "slot": "panel"}]
        assert c.get("/api/panels").json() == [{
            "name": "dummy",
            "data": {
                "title": "Dummy panel",
                "rows": [
                    {"label": "Challenges", "value": 2},
                    {"label": "Schema", "value": "1.3"},
                    {"label": "Session", "value": "comp"},
                    {"label": "Empty", "value": None},
                ],
                "columns": None,
                "table": None,
            },
        }]


def test_table_layout_panel(tmp_path, dummies):
    with make_client(tmp_path, allow=["dummy-table"]) as c:
        add(c, "one", 50)
        data = c.get("/api/panels").json()[0]["data"]
    assert data["rows"] is None
    assert data["columns"] == ["Name", "Points", "Ratio"]
    assert data["table"] == [["one", 50, 0.5]]


def test_panel_skipped_when_not_allowlisted(tmp_path, dummies):
    with make_client(tmp_path, allow=["dummy"]) as c:
        assert loaded_names(c) == ["dummy"]
    assert "dummy_panels.good" in sys.modules
    assert "dummy_panels.unlisted" not in sys.modules  # LR-1: never imported to find out its NAME


def test_allowlisted_but_not_installed(tmp_path, dummies, caplog):
    with caplog.at_level(logging.WARNING, "sarissa.plugins"):
        with make_client(tmp_path, allow=["dummy", "nowhere"]) as c:
            assert loaded_names(c) == ["dummy"]
    assert "'nowhere' not installed" in caplog.text


# --- LR-2 API major / LR-3 load-time isolation --------------------------------

def test_api_mismatch_skipped(tmp_path, dummies, caplog):
    with caplog.at_level(logging.WARNING, "sarissa.plugins"):
        with make_client(tmp_path, allow=["dummy", "dummy-wrong-api"]) as c:
            assert loaded_names(c) == ["dummy"]
    assert "'dummy-wrong-api' skipped" in caplog.text and "incompatible" in caplog.text


@pytest.mark.parametrize("bad", ["dummy-badname", "dummy-baddescribe", "dummy-missing", "dummy-broken-import"])
def test_broken_plugin_skipped_core_continues(tmp_path, dummies, caplog, bad):
    with caplog.at_level(logging.WARNING, "sarissa.plugins"):
        with make_client(tmp_path, allow=["dummy", bad]) as c:
            assert loaded_names(c) == ["dummy"]
            assert panel_names(c) == ["dummy"]
            assert c.get("/api/health").json() == {"status": "ok"}
    assert f"{bad!r} skipped" in caplog.text


# --- LR-3 call-time isolation ---------------------------------------------------

def test_panel_exception_isolated(tmp_path, dummies, caplog):
    with caplog.at_level(logging.WARNING, "sarissa.plugins"):
        with make_client(tmp_path, allow=["dummy", "dummy-raises"]) as c:
            assert loaded_names(c) == ["dummy", "dummy-raises"]
            assert panel_names(c) == ["dummy"]
    assert "RuntimeError" in caplog.text


@pytest.mark.parametrize("bad", ["dummy-invalid", "dummy-nonfinite"])
def test_invalid_panel_data_dropped(tmp_path, dummies, caplog, bad):
    with caplog.at_level(logging.WARNING, "sarissa.plugins"):
        with make_client(tmp_path, allow=["dummy", bad]) as c:
            assert panel_names(c) == ["dummy"]
    assert repr(bad) in caplog.text


# --- /api/panels is read-only ---------------------------------------------------

def test_panels_read_only(tmp_path, dummies):
    with make_client(tmp_path, allow=["dummy", "dummy-mutating"]) as c:
        cid = add(c, "one", 100)
        assert c.post(f"/api/challenges/{cid}/timer/start").status_code == 200
        assert c.post("/api/session/save").status_code == 200
        path = tmp_path / "comp.json"
        before_bytes = path.read_bytes()
        before = copy.deepcopy(c.app.state.sessions.current)

        first = c.get("/api/panels").json()
        second = c.get("/api/panels").json()

        assert path.read_bytes() == before_bytes
        assert c.app.state.sessions.current == before
        assert c.app.state.sessions.last_saved is not None
        # The mutating plugin scribbled on its copy only; its next call still sees the real session.
        assert [p["name"] for p in first] == ["dummy", "dummy-mutating"]
        assert first == second
        timer = c.get(f"/api/challenges/{cid}/timer").json()
        assert timer["challenge_timer_started_at"] == before["challenges"][0]["challenge_timer_started_at"]
        assert c.get("/api/export").json()["challenges"][0]["points"] == 100


def test_panels_409_no_session(tmp_path, dummies):
    with make_client(tmp_path, allow=["dummy"], name=None) as c:
        r = c.get("/api/panels")
        assert r.status_code == 409
        assert c.get("/api/plugins").status_code == 200  # plugin list needs no session


def test_panel_input_is_the_export(tmp_path, dummies, monkeypatch):
    seen = []
    with make_client(tmp_path, allow=["dummy"]) as c:
        add(c, "one")
        plugin = c.app.state.panels[0].plugin
        monkeypatch.setattr(plugin, "panel", lambda export: seen.append(export) or {"title": "t", "rows": []})
        assert panel_names(c) == ["dummy"]
        export = c.get("/api/export").json()
    (got,) = seen
    assert got["schema_version"] == "1.3" and got["tool"] == "Sarissa"
    assert got["challenges"] == export["challenges"]
    assert "challenge_timer_started_at" not in got["challenges"][0]


# --- Config (LR-1 sources) --------------------------------------------------------

def test_config_allowlist_read(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[plugins]\nallow = ["dummy", "dummy-table"]\n', encoding="utf-8")
    assert plugins.read_allowlist(cfg) == ["dummy", "dummy-table"]


@pytest.mark.parametrize("text", [None, "not = [valid toml", "[plugins]\nallow = \"dummy\"\n",
                                  "[plugins]\nallow = [1]\n", "plugins = 3\n", ""])
def test_config_missing_or_malformed_is_empty(tmp_path, text):
    cfg = tmp_path / "config.toml"
    if text is not None:
        cfg.write_text(text, encoding="utf-8")
    assert plugins.read_allowlist(cfg) == []


@pytest.fixture
def launch(monkeypatch, tmp_path):
    """main() with uvicorn, the browser timer and the console faked; config + sessions in tmp."""
    calls = types.SimpleNamespace(app=None)

    class FakeTimer:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    class FakeConsole:
        def print(self, *args, **kwargs):
            pass

    def fake_run(app, **kwargs):
        calls.app = app

    real_create_app = sarissa.main.create_app
    monkeypatch.setattr(sarissa.main, "threading", types.SimpleNamespace(Timer=FakeTimer))
    monkeypatch.setattr(sarissa.main, "uvicorn", types.SimpleNamespace(run=fake_run))
    monkeypatch.setattr(sarissa.main, "Console", FakeConsole)
    monkeypatch.setattr(sarissa.main, "create_app", lambda allow=(): real_create_app(tmp_path / "s", allow))
    monkeypatch.setattr(plugins, "CONFIG_PATH", tmp_path / "config.toml")
    return calls


def test_cli_allow_plugin_adds_to_config(launch, tmp_path, dummies):
    (tmp_path / "config.toml").write_text('[plugins]\nallow = ["dummy"]\n', encoding="utf-8")
    sarissa.main.main(["--allow-plugin", "dummy-table"])
    assert [p.name for p in launch.app.state.panels] == ["dummy", "dummy-table"]


def test_cli_without_config_or_flag_loads_nothing(launch, dummies):
    sarissa.main.main([])
    assert launch.app.state.panels == []


# --- Panels tab (static: no headless browser in the suite) ----------------------

@pytest.fixture
def page(tmp_path):
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        return c.get("/").text


def test_panels_tab_hidden_by_default(page):
    assert re.search(r'<button[^>]*id="tabPanels"[^>]*\bhidden\b[^>]*>Panels</button>', page)
    assert re.search(r'<main id="panelsView"[^>]*\bhidden\b', page)
    assert page.index('id="tabGenerate"') < page.index('id="tabPanels"')


def test_panels_ui_textcontent_only(page):
    js = page[page.index("<script>"):page.index("</script>")]
    block = js[js.index("/* ---------- Panels (plugin slot"):js.index("/* ---------- Keyboard shortcuts")]
    assert 'api("/api/panels")' in block and 'api("/api/plugins")' in block
    assert "textContent" in block and "replaceChildren" in block
    assert 'panels: ["tabPanels", "panelsView"]' in js
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "Function(",
                   "localStorage", "sessionStorage", "alert(", "confirm(", "prompt("):
        assert banned not in js, banned
    # LR-4: nothing a plugin sends is treated as markup, style or script.
    assert ".style" not in block and "setAttribute" not in block and "src" not in block


def test_no_plugins_routes_shape(tmp_path):
    with make_client(tmp_path) as c:
        paths = {getattr(r, "path", "") for r in c.app.routes}
        assert {"/api/plugins", "/api/panels"} <= paths
        assert c.get("/api/export").json()["schema_version"] == "1.3"
