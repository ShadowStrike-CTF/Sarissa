# Sarissa — Phase 14 keyboard shortcuts. Sarissa-side HTML/JS only (no headless browser in the suite).
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import re

import pytest
from fastapi.testclient import TestClient

from sarissa.main import create_app

LISTENER = 'document.addEventListener("keydown"'


@pytest.fixture
def html(tmp_path):
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        r = c.get("/")
    assert r.status_code == 200
    return r.text


def script(page):
    return page[page.index("<script>"):page.index("</script>")]


def block(js, start, end):
    """The source from `start` up to and including the next `end` (a function or object body)."""
    i = js.index(start)
    return js[i:js.index(end, i) + len(end)]


def fn(js, name):
    return block(js, f"function {name}(", "\n}\n")


def keymap(js):
    return block(js, "const KEYMAP = {", "\n};\n")


def listener(js):
    return block(js, LISTENER, "\n});\n")


def shortcuts_js(js):
    return js[js.index("/* ---------- Keyboard shortcuts"):js.index("/* ---------- Boot")]


def test_shortcut_panel_toggle(html):
    js = script(html)
    panel = re.search(r'<div id="shortcutPanel"[^>]*>', html).group(0)
    assert "hidden" in panel, "panel starts closed"
    # Outside every tab view, so ? works on Cockpit, Parse and Generate alike.
    assert html.index('id="shortcutPanel"') > html.rindex("</main>")
    assert '"?": toggleShortcutPanel' in keymap(js)
    assert '$("shortcutPanel").hidden = !$("shortcutPanel").hidden' in fn(js, "toggleShortcutPanel")
    # Two-column table built from one list, via textContent.
    rows = block(js, "const SHORTCUTS = [", "\n];\n")
    for key in ("1", "2", "3", "j", "k", "n", "s", "t", "Space", "?", "Esc"):
        assert f'["{key}", ' in rows, key
    assert 'el("td", { textContent: key }), el("td", { textContent: action })' in js
    assert "innerHTML" not in html


def test_escape_closes_panel(html):
    esc = block(listener(script(html)), 'if (ev.key === "Escape") {', "return;\n  }")
    assert '$("shortcutPanel").hidden = true;' in esc
    assert "closeLaunch()" in esc, "the old launch-overlay Escape still works"


def test_escape_always_fires(html):
    js = script(html)
    assert js.count(LISTENER) == 1, "one listener owns every shortcut"
    body = listener(js)
    esc = body.index('ev.key === "Escape"')
    # Escape is handled before every guard that could swallow it.
    for guard in ("isTyping(document.activeElement)", "ev.ctrlKey", '!$("launch").hidden) return'):
        assert esc < body.index(guard), guard


def test_shortcut_suppressed_in_input(html):
    js = script(html)
    assert '["INPUT", "TEXTAREA", "SELECT"].includes(node.tagName)' in fn(js, "isTyping")
    body = listener(js)
    assert "if (isTyping(document.activeElement)) return;" in body
    assert body.index("isTyping(document.activeElement)") < body.index("KEYMAP[key]")
    km = keymap(js)
    for key in ("j", "k", "n", "s", "t", "Space"):
        assert re.search(rf"^  {key}: ", km, re.M), key
    # A handled key is swallowed so it doesn't also land in the box it just focused.
    assert body.index("ev.preventDefault()") < body.index("guard(action)()")


def test_j_k_navigation_wraps(html):
    js = script(html)
    km = keymap(js)
    assert "j: onCockpit(() => stepSelection(1))" in km
    assert "k: onCockpit(() => stepSelection(-1))" in km
    step = fn(js, "stepSelection")
    assert "const list = displayOrder();" in step, "j/k walk the order the cockpit draws"
    assert "(i + dir + list.length) % list.length" in step, "wraps both ways"
    assert "dir > 0 ? 0 : list.length - 1" in step, "no selection: j starts at the top, k at the bottom"
    assert "displayOrder()" in fn(js, "renderChallengeList")


def test_s_marks_solved(html):
    js = script(html)
    assert "s: withSelected(markSolved)" in keymap(js)
    body = fn(js, "markSolved")
    assert 'if (c.status === "solved") return;' in body, "forward-only: no untick"
    assert '`/api/challenges/${c.id}/score`, { method: "PATCH", json: { solved: true } }' in body
    assert "solved: false" not in html


def test_t_starts_stops_timer(html):
    js = script(html)
    assert "t: withSelected(toggleChallengeTimer)" in keymap(js)
    body = fn(js, "toggleChallengeTimer")
    assert '`/api/challenges/${c.id}/timer/${running ? "stop" : "start"}`, { method: "POST" }' in body
    # The ▶ Timer button and t share one code path.
    assert "onclick: guard(() => toggleChallengeTimer(c))" in fn(js, "renderChallenge")
    assert js.count("/timer/${") == 1


def test_n_focuses_notes(html):
    js = script(html)
    row = fn(js, "renderChallenge")
    assert 'el("textarea", { className: "notes"' in row and "maxLength: 10000" in row
    assert 'notes.dataset.field = "notes";' in row
    assert '`/api/challenges/${c.id}`, { method: "PATCH", json: { notes: notes.value } }' in row
    assert 'textarea[data-chal="${CSS.escape(c.id)}"]`)?.focus()' in keymap(js)


def test_space_starts_session_timer_only_when_stopped(html):
    js = script(html)
    km = keymap(js)
    assert 'Space: onCockpit(() => { if (session && !session.timer.started_at) return updateTimer({ action: "start" }); })' in km
    assert "reset" not in km.replace("reset stays click-only", "")
    assert 'ev.key === " " ? "Space"' in listener(js)


def test_selection_frontend_only(html, tmp_path):
    js = script(html)
    for line in js.splitlines():
        if "selectedId" in line:
            assert "api(" not in line and "fetch(" not in line, line
    assert "localStorage" not in html and "sessionStorage" not in html
    # Shortcuts reach the server only through the functions the buttons already use.
    block_js = shortcuts_js(js)
    assert "api(" not in block_js and "fetch(" not in block_js
    # No new colours: the highlight uses palette tokens.
    rule = re.search(r"\.chal\.selected \{([^}]*)\}", html).group(1)
    assert "var(--crimson-hi)" in rule and "#" not in rule
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        paths = {getattr(r, "path", "") for r in c.app.routes}
    assert not any(w in p for p in paths for w in ("shortcut", "select", "keyboard"))
