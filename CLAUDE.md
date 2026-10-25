# Sarissa — CTF Dashboard
Rapid-access CTF dashboard for digital forensics competitions.
by ShadowStrike. MIT.

## Tech stack
- Python 3.11
- FastAPI + uvicorn (backend, port 7331 ALWAYS — no dynamic port)
- httpx (runtime — loopback-only proxy to Poligon on :7333, Phase 8)
- Vanilla HTML/CSS/JS single-file frontend
- python-magic (magic byte detection — python-magic-bin required on Windows)
- hashlib stdlib (MD5/SHA1/SHA256/SHA512)
- json stdlib (session storage at ~/.sarissa/sessions/<name>.json)
- PyInstaller (Windows primary)

## Architecture
Named sessions per competition. Auto-save every 60 seconds.
Four DF quick tools: hash calculator, timestamp converter, file type inspector,
string extractor. All four always visible on the Cockpit tab — no navigation required.
Challenge status is ONE-WAY: unsolved → in_progress → solved. No reversing via API.
Timer: countdown (primary) + elapsed toggle. Both modes always available.

## Key invariants
- Port: 7331 ALWAYS
- Magic bytes only for type detection — never file extension
- Hash calculator: all four algorithms always together (never partial)
- String extractor min-length: CLI --min-strings only; UI default fixed at 4
- No external network calls EVER during competition use
- Session auto-saves every 60 seconds to ~/.sarissa/sessions/<name>.json

## WHAT NOT TO DO
- Never use tkinter (session-scoped, breaks on relaunch)
- Never use a port other than 7331
- Never trust file extension for type detection
- Never allow challenge status to move backwards via the API
- Never make external network calls
- Never expose --min-strings in the web UI (v1.0.0 — CLI only)
- Never use git add -A — always path-scoped adds

## PACKAGING

**Entry point:** `src/sarissa/__main__.py` — thin wrapper that calls `sarissa.main.main()`
(uvicorn + `webbrowser.open` + `--min-strings` all live in `main.py`)
**Spec:** `sarissa.spec` (repo root) — build with `pyinstaller sarissa.spec --clean`
(`.gitignore` ignores `*.spec`; `!sarissa.spec` re-includes this one)
**Target platform:** Windows (exe built locally — not in cloud)
**Port constant:** `PORT = 7331` in `src/sarissa/main.py` — single source of truth (tests import it).
Never add a second port constant in `__main__.py` or the spec.

### Windowed exe (console=False)
- `sys.stdout` / `sys.stderr` are `None` in a windowed exe. uvicorn's log formatter calls
  `sys.stdout.isatty()` at startup and crashes before binding the port.
- `__main__.py` points them at `os.devnull` when `None`. Do not remove this guard.

### python-magic on Windows
- Install `python-magic-bin` (not `python-magic`) — ships libmagic.dll
- `pyinstaller-hooks-contrib` handles the DLL collection automatically (`hook-magic.py`:
  `collect_data_files('magic')` + `collect_dynamic_libs('magic')`)
- If `magic` import fails at runtime: verify `magic` is in `hiddenimports` in sarissa.spec

### Frozen path handling
- Already handled: `static_dir()` in `main.py` uses `sys._MEIPASS/sarissa/static` when frozen,
  `Path(__file__).parent / "static"` otherwise.
- Spec `datas`: `('src/sarissa/static', 'sarissa/static')` — must match `static_dir()`.
- Session files live in `~/.sarissa/sessions/` (home dir), so they are unaffected by freezing.

### Build command (run locally on Windows)
```
pip install .
pip install pyinstaller pyinstaller-hooks-contrib python-magic-bin
pyinstaller sarissa.spec --clean
```
(`pip install .` pulls in the runtime deps — fastapi, uvicorn, rich — that PyInstaller bundles.)
Output: `dist/sarissa.exe`

## Phase 7 — Treska integration panel

Architecture: Option A — browser fetch. The Sarissa frontend fetches
directly from Treska's API at http://localhost:7332. No server-to-server
calls. No import of treska code. No packaging dependency on Treska.

Panel: new "Parse" tab in Sarissa alongside the existing session/tools tabs.
Name: "Parse" (matches Treska's verb — parse a zip).

Layout:
- Drop zone: same drag-drop pattern as Treska's own UI (zip upload)
- On upload: browser POSTs to http://localhost:7332/api/parse
- Results: flagged files table, SQLite schemas, full inventory (collapsible)
- Treska offline: show inline banner "Treska not running on :7332 —
  start it with python -m treska" — not an error, just a state
- Export JSON button (client-side Blob download)

Tokens: Sarissa crimson (#922b21) throughout. Do NOT use Treska mid-red (#e74c3c).
All DOM text via textContent — CTF zip filenames can be hostile.
No alert/confirm/prompt. No innerHTML with data. No green.

New routes on Sarissa server: none. The fetch is browser-to-Treska only.
New tests: web tests for the new tab rendering (TestClient). No mocking
of the Treska API — test the Sarissa-side HTML/JS only.

Implementation notes (Phase 7 PR):
- Tabs: header `Cockpit | Parse`. Cockpit = the three columns (challenges, timer, all four tools).
  Parse swaps them out; switching back is one click and keeps the parse results.
- Single Treska URL constant: `TRESKA` in `src/sarissa/static/index.html`. No Python in
  `src/sarissa/` references Treska.
- CORS dependency: Treska must send `Access-Control-Allow-Origin` for `http://127.0.0.1:7331`
  (and `http://localhost:7331`). Until it does, the Parse tab shows a "blocking requests from
  Sarissa (CORS)" banner, distinct from the offline banner, and never uploads.
- Treska's error body is `{"error": "..."}` (422 = not a parseable zip).

## Phase 8 — Poligon Generate tab

Architecture: Option B — server-side proxy. The browser calls Sarissa; Sarissa calls Poligon
at http://127.0.0.1:7333. The browser never talks to Poligon, so no CORS surface. This is the
only Sarissa route that talks to a sibling tool, and it is loopback-only — "no external
network calls" still holds. Phase 7's "no Sarissa routes, browser-only" rule applies to Treska only.

Tabs: header `Cockpit | Parse | Generate`. Switching tabs keeps each tab's state.

Poligon contract (verified against poligon main 09cda1e):
- `POST /api/generate {template, seed, difficulty}` → JSON `{scenario_id, template, difficulty, …, download_url}`
  (NOT zip bytes). 400 + `{"detail": "..."}` on bad input.
- `GET /api/download/{scenario_id}` → the challenge zip.
- `GET /api/health` → `{"status": "ok", "port": 7333}`.

Sarissa routes:
- `GET /api/health` → `{"status": "ok"}` (G.0 gate target).
- `POST /api/generate` — strict JSON body (pydantic, strict mode, extra forbidden):
  template ∈ android | filesystem | evidence; seed = int (not bool/str/float); difficulty = int 1–3
  (not bool). Non-JSON content type → 422 (blocks cross-site simple-POST CSRF).
  Two calls to Poligon (generate, then download); returns the zip as `application/zip` with
  `Content-Disposition: attachment; filename="<template>_<seed>_d<difficulty>.zip"`.
  Errors: 422 invalid input · 503 Poligon offline (ConnectError) · 504 Poligon timed out ·
  502 any other Poligon failure (non-200, bad JSON, bad scenario_id).
- `GET /api/poligon/health` → `{"status": "online", "poligon_status": <code>, "port": 7333}` or
  `{"status": "offline", "port": 7333}`. Always 200.

Invariants (LOCKED):
- `POLIGON_PORT = 7333` in `src/sarissa/main.py` — single constant. Never hardcoded elsewhere;
  the frontend never contains 7333 (banner text takes the port from `/api/poligon/health`).
- Banner states: offline / online (banner hidden) / error (Poligon answered, health not 200).
  No CORS-blocked state — the proxy removes the CORS surface.
- Form: template select, seed number input (default 42), difficulty select (1/2/3), Generate button.
- "Last generated: <template> · seed <seed> · d<difficulty>" — JS variable only (no localStorage,
  no server state); cleared on reload.
- "Download again" = Blob URL of the last generated zip held in memory — no second Poligon call,
  no GET generate route.
- All DOM text via textContent. No innerHTML. No green. No animations or transitions.
- httpx is a runtime dependency (pyproject `dependencies`). Pure Python, imported at module top,
  so PyInstaller collects it without a hiddenimport.
- Tests mock Poligon at the httpx transport layer (`httpx.MockTransport`) via the module-level
  `poligon_client()` factory in `main.py` — never a live Poligon in the test suite.

## Phase 9 — Session export

Route: `GET /api/export` (in `create_app()`, `main.py`). Read-only — does not save.
Returns the active session as `application/json` with
`Content-Disposition: attachment; filename="sarissa-<name>-<YYYYMMDD>.json"` (UTC date; session
names are already restricted to `[A-Za-z0-9_-]`). No active session → 409 via the app-wide
`NoActiveSession` handler (same as every other session route — not 404).

Schema v1.0 (Zapis Phase 6 ingestion):
```
{
  "schema_version": "1.0",
  "tool": "Sarissa",
  "session": {"name", "created_at", "updated_at", "exported_at", "timer": {mode, duration_seconds, started_at}},
  "challenges": [ ...challenge objects as stored, incl. per-challenge notes... ]
}
```

Invariants:
- Export only what the session actually stores — never fabricate or default fields.
- The four quick tools are stateless (results go to the browser, never into the session), so
  v1.0 has no `results` key. Adding one needs the tools to persist results first → schema bump.
- Frontend: `Export JSON` button + `#exportStatus` span in the header session bar (visible on every
  tab). Blob download; errors shown inline via textContent. No alert/confirm/prompt, no innerHTML.

## Phase 10 (v1.3.0)
- Favicon: inline `<link rel="icon" href="data:image/svg+xml;base64,...">` in `index.html` `<head>`.
  Hand-drawn pumpkin SVG in Sarissa crimson (`#922b21`, sides `#7b241c`, brown stem) — no emoji,
  no green, no external file. The HTML is static, so the base64 is a literal (encoded once, never
  per request) and there is no Python favicon constant.
- Visibility gates (intervals unchanged): `treskaStatus()` returns early unless
  `document.visibilityState === "visible"`; the 15 s session refresh skips hidden tabs; one
  `visibilitychange` listener re-runs both on return (Treska only if the Parse tab is open).
- Treska has no timer — it is probed on demand (Parse tab click, upload). Do not add polling.
- Tests: 148 → 151 (`tests/test_phase10.py`).

## Phase 11 — Challenge scoring + strategy view (v1.4.0)

Field mapping (R-approved — the brief's names map onto fields challenges already store):
| Brief name | Stored as | Type | Default | Meaning |
|---|---|---|---|---|
| `point_value` | `points` | int ≥ 0 | 0 | Point value (0 = unset) |
| `solved` | `status == "solved"` | derived | false | Flag submitted (one-way, never unticked) |

No new stored fields, no new tables, no session-file migration. `solved` is NOT a second flag
beside `status` — two sources of truth would drift and a reversible tick would move status backwards.

Routes:
- `PATCH /api/challenges/{id}/score` (plural prefix — same router as every challenge route).
  Body strict, extra forbidden: `point_value` StrictInt 0–9999, `solved` StrictBool, both optional
  (omitted = unchanged). `point_value` → writes `points`. `solved: true` → advances status to solved
  and sets `solved_at` (no-op if already solved). `solved: false` on a solved challenge → 409
  (one-way, same rule as `/status`); on an unsolved one → no-op. The whole body is checked before
  anything is written. Returns the challenge as stored. 404 unknown id · 409 no session · 422 bad body.
- `GET /api/session/score` → `{"total_points", "secured_points", "remaining_points", "solved_count",
  "total_challenges"}`. Point sums count only challenges with `points > 0`; secured = those solved;
  remaining = total − secured. `solved_count` / `total_challenges` count every challenge.
  409 no session. Lives on a `score_router` in `api/challenges.py` (avoids a session↔challenges cycle).

UI:
- Score panel `#scorePanel` in the header session bar: "<secured> / <total> pts". Muted by default,
  `--crimson` when secured > 80% of total (total > 0). Re-fetched after every challenge change.
- Per challenge: number input (0–9999) for points, saves on blur/Enter via the score PATCH. The
  existing forward-only "Solved" button is the tick — no untick. Solved rows get reduced opacity;
  they are never hidden.
- Sort select `#chalSort` beside the Challenges heading: "Default" (existing order: in progress,
  unsolved, solved) / "By points (high → low)". JS variable only — no storage, no server state.
- textContent only. No innerHTML, no browser dialogs, no green, no transitions or animations.

Export: unchanged — `schema_version` stays `"1.0"`. Challenges already carry `points` and `status`,
so Zapis gets the scoring data without a schema bump. (The brief's v1.1 bump was dropped: nothing
new is stored, and export never fabricates fields.)

Invariants:
- INV-1: Scoring uses the existing challenge fields (`points`, `status`) — no new fields or tables.
- INV-2: The score panel shows `GET /api/session/score` — totals are never computed in the frontend.
- INV-3: `points = 0` means unset — excluded from point totals.
- INV-4: Sort is frontend-only UI state — the server always returns creation order.
- INV-5: Export schema stays v1.0 — existing consumers (Zapis Ph6) see no change.
- INV-6: Ph1–Ph10 tests stay green — no regressions.

What NOT to do:
- ❌ Compute score totals in the frontend — `/api/session/score` owns the maths
- ❌ Include `points = 0` in `total_points`
- ❌ Hide solved challenges — de-emphasise only
- ❌ Let `solved` (or anything else) move status backwards
- ❌ Persist sort order — server-side or in browser storage
- ❌ Add `point_value` / `solved` keys to stored challenges or the export

Tests (`tests/test_scoring.py`, 151 → 161):
`test_patch_challenge_score_point_value`, `test_patch_challenge_score_solved`,
`test_patch_challenge_score_partial`, `test_get_session_score_totals`,
`test_get_session_score_excludes_zero_value`, `test_export_scoring_fields`,
`test_score_409_no_session`, `test_patch_score_cannot_unsolve`, `test_patch_score_validation`,
`test_cockpit_scoring_ui`.

## Phase 12 — Challenge categories + filter bar (v1.5.0)

Field (R-approved): the brief's new field already exists, so nothing new is stored.
| Field | Stored as | Type | Default | Meaning |
|---|---|---|---|---|
| `category` | `category` (since Phase 2) | str ≤ 64 chars | `""` | Free-text category ("Forensics", "Crypto", "OSINT") |

No new fields, no new tables, no session-file migration. Content is not validated: any string,
empty included, is stored exactly as sent. The only rule is the 64-char cap that create/edit
already apply, and the new route uses the same cap so all three entry points agree.

Routes:
- `PATCH /api/challenges/{id}/category` (plural prefix, the same router as every challenge route,
  not the brief's singular `/api/challenge/`). Body strict, extra forbidden:
  `{"category": StrictStr ≤ 64}`, required. Returns the challenge as stored.
  404 unknown id · 409 no session · 422 bad body.
- `GET /api/session/categories` returns a bare JSON list of the unique non-empty categories,
  sorted (plain case-sensitive `sorted()`), e.g. `["Crypto", "Forensics", "OSINT"]`. A session with
  no categories → `[]` (200). 409 no session. Lives on `score_router` in `api/challenges.py`
  (avoids a session↔challenges cycle).

UI:
- Per challenge: small text input for the category (replaces the read-only tag). Saves on
  blur/Enter through the category PATCH. textContent only.
- Filter bar `#catFilter` under the Challenges heading: an "All" chip plus one chip per category
  from `GET /api/session/categories`. "All" (the default) shows every challenge. Category chips
  toggle, and selecting several is an OR filter. Hidden when no challenge has a category.
  JS variable only: no storage, no server state. Tally and score panel stay unfiltered.
- No innerHTML, no browser dialogs, no green, no transitions or animations.

Export: unchanged. `schema_version` stays `"1.0"`, because challenges have carried `category`
since v1.0. (The brief's v1.2 bump was dropped for the same reason as Ph11's v1.1 bump: nothing new
is stored.)

Invariants:
- INV-1: `category` lives in the existing challenge dict. No new fields or tables.
- INV-2: `GET /api/session/categories` returns unique non-empty values only. `""` is excluded.
- INV-3: The filter is frontend-only UI state. The server always returns creation order.
- INV-4: Category display uses textContent only. No innerHTML with user data.
- INV-5: The export schema stays v1.0. Zapis Ph6 sees no change.
- INV-6: Ph11 scoring (`points`, `status`, `/score`) is untouched. Ph1–Ph11 tests stay green.

What NOT to do:
- ❌ Validate category content (any string goes; only the existing 64-char cap applies)
- ❌ Trim or normalise category server-side (the frontend trims before sending, like the add form)
- ❌ Persist filter state, server-side or in browser storage
- ❌ Show the filter bar when no categories are set
- ❌ innerHTML with category data (textContent only)
- ❌ Break Ph11 fields or the test suite

Tests (`tests/test_categories.py`, 161 → 169):
`test_patch_challenge_category`, `test_patch_challenge_category_empty_string`,
`test_get_session_categories_returns_sorted_unique`, `test_get_session_categories_excludes_empty`,
`test_get_session_categories_empty_session`, `test_export_category_field`,
`test_category_409_no_session`, `test_cockpit_category_ui`.

## Phase 13 — Per-challenge timer (v1.6.0)

Each challenge gets its own stopwatch, separate from the session countdown/elapsed timer.
The server stores only "seconds banked" and "when the clock was last started". The browser does
the live counting.

New fields per challenge (stored in the existing challenge dict, persisted server-side):
| Field | Type | Default | Meaning |
|---|---|---|---|
| `challenge_time_seconds` | int ≥ 0 | 0 | Total time banked on this challenge (whole seconds) |
| `challenge_timer_started_at` | ISO8601 str \| null | null | When the challenge timer last started; null when stopped |

New challenges get both defaults on create. Client-sent timer fields are ignored on create and
rejected on edit (`PATCH /api/challenges/{id}` is already `extra="forbid"`). Old session files:
`SessionManager.load` backfills both fields with `setdefault` (0 / null). From then on they really
are stored, so export still never fabricates. The file is rewritten at the next save.

Routes (R-approved: plural prefix, the same router as every challenge route, not the brief's
singular `/api/challenge/`). All three return `{"id", "challenge_timer_started_at",
"challenge_time_seconds"}`. Errors: 404 unknown id · 409 no session (app-wide `NoActiveSession` handler).
- `POST /api/challenges/{id}/timer/start` sets `challenge_timer_started_at` to the server's `utc_now()`.
  Idempotent: if it is already running, it returns the current state unchanged (start time kept).
- `POST /api/challenges/{id}/timer/stop` adds `max(0, int(now − started_at))` seconds to
  `challenge_time_seconds` and sets `challenge_timer_started_at` to null. Idempotent: if it is already
  stopped, it returns the current state unchanged.
- `GET /api/challenges/{id}/timer` returns the current state. Read-only.
- Start/stop save the session immediately, like `PUT /api/session/timer`. A crash never loses a running start time.

Export → schema `"1.3"` (R-approved; 1.1 and 1.2 never existed because Ph11/Ph12 dropped their bumps).
Challenges gain `challenge_time_seconds`. `challenge_timer_started_at` is stripped from the export.
Additive: every v1.0 key is unchanged. This supersedes the "stays v1.0" notes in Ph9/Ph11/Ph12.

UI:
- Per challenge: a timer readout (`.ctimer`, mono, HH:MM:SS) plus a start/stop button in the meta row,
  labelled "▶ Timer" / "■ Stop". It is not "Start", because that label already belongs to the status button
  (unsolved → in progress).
- Live display = `challenge_time_seconds` + time since `challenge_timer_started_at`, computed in the
  browser by the existing 250 ms `tick()` (no new interval), using the session clock offset.
- Start/stop responses are merged into the local challenge list. No polling loop.
- Running: crimson-hi text with a static "●" indicator. Stopped: muted, showing banked time.
- textContent only. No innerHTML, no browser dialogs, no green, no transitions or animations.

Invariants:
- INV-1: The challenge timer is INDEPENDENT of the session timer. Different concerns, different fields.
- INV-2: `challenge_timer_started_at` is NOT exported. Only `challenge_time_seconds` is.
- INV-3: The client computes the live display. The server never sends a "current elapsed" field.
- INV-4: Start and stop are idempotent. No error if the timer is already in that state.
- INV-5: Timer fields live in the existing challenge dict. No new tables.
- INV-6: Ph11 scoring + Ph12 categories are untouched. Ph1–Ph12 tests stay green (the three
  `schema_version == "1.0"` assertions move to `"1.3"`).

What NOT to do:
- ❌ Export `challenge_timer_started_at`. Only `challenge_time_seconds` is exported.
- ❌ Compute live elapsed on the server. The client computes the display.
- ❌ Tie the challenge timer to session timer state (or auto-stop it on status changes)
- ❌ Raise an error on an idempotent start/stop. Return the current state.

Tests (`tests/test_challenge_timer.py`, 169 → 177):
`test_timer_start_sets_timestamp`, `test_timer_stop_accumulates_seconds`, `test_timer_stop_idempotent`,
`test_timer_start_idempotent`, `test_timer_get_state`, `test_export_schema_v1_3`,
`test_timer_independent_of_session_timer`, `test_timer_409_no_session`.

## Phase 14 — Keyboard shortcuts (v1.7.0)

Pure frontend: one `keydown` listener on `document` in `src/sarissa/static/index.html`. No new routes,
no new stored fields. Shortcuts call only routes the buttons already use.

| Key | Action |
|---|---|
| `1` / `2` / `3` | Switch to the Cockpit / Parse / Generate tab |
| `j` | Select the next challenge (wraps last → first) |
| `k` | Select the previous challenge (wraps first → last) |
| `n` | Focus the notes textarea of the selected challenge |
| `s` | Mark the selected challenge solved (forward-only; no-op if already solved) |
| `t` | Start/stop the selected challenge's timer (Ph13) |
| `Space` | Start the session timer if it is stopped (no-op while it runs) |
| `?` | Open/close the shortcut panel |
| `Escape` | Close the shortcut panel (and the launch overlay, as before). Always fires |

R-approved deviations from the brief:
- Tabs are Cockpit / Parse / Generate (there is no Notes tab), so `1`/`2`/`3` map to those.
- `s` does not toggle. Solved is one-way (Ph11 `/score` returns 409 on `solved: false`), so `s` sends
  `PATCH /api/challenges/{id}/score {"solved": true}` (plural prefix, as every challenge route) and does
  nothing on a solved challenge. It never sends `solved: false`.
- `Space` does not stop. The session timer only has `start` (which restarts a running clock) and `reset`.
  So Space starts a stopped timer and does nothing while it runs. Reset stays click-only.
- `n` needed a notes box, and none existed (`notes` was stored and exported, but not editable). Each
  challenge row gains a notes textarea (≤ 10 000 chars, the existing cap). It saves on blur if changed,
  through the existing `PATCH /api/challenges/{id} {"notes": ...}`. No trim: notes are free text.

Listener rules (in this order):
1. `Escape` is handled first, before any focus check. It closes the shortcut panel and the launch
   overlay (the old launch-overlay Escape listener is folded into the one listener).
2. Ignored when Ctrl/Meta/Alt is held (browser shortcuts like Ctrl+1 keep working) or on key-repeat.
3. Ignored when an `<input>`, `<textarea>` or `<select>` has focus. Typing in category/points/notes never
   fires a shortcut.
4. Ignored while the launch overlay (session picker) is open.
5. `Space` is also ignored when a button has focus (the browser's own Space = click).
6. `j`/`k`/`n`/`s`/`t`/`Space` act only while the Cockpit tab is visible.
A handled key calls `preventDefault()`, so `n` does not type an "n" into the box it just focused.

Selected challenge:
- JS variable `selectedId` only. Never stored, never sent to the server.
- `j`/`k` walk the display order (category filter + sort), the same list the cockpit draws.
- If the selected challenge is filtered out or deleted, `n`/`s`/`t` do nothing and the next `j`/`k`
  starts again from the first/last row.
- Highlight: `.chal.selected` outline in `--crimson-hi`. Existing tokens only.

Shortcut panel `#shortcutPanel`: a fixed inline overlay outside `<main>` (works on every tab). It is not
modal and not a browser dialog. A two-column table (key | action) built with `el()`/textContent from one
`SHORTCUTS` array.

Invariants:
- INV-1: Pure JS keydown listener. No new endpoints. Shortcuts call only existing routes
  (`/score`, `/timer/start|stop`, `PATCH /api/challenges/{id}` for notes, `PUT /api/session/timer`).
- INV-2: Every shortcut except `Escape` is suppressed while an input/textarea/select has focus.
- INV-3: Selected challenge state is frontend-only. Never sent to the server, never in browser storage.
- INV-4: No browser dialogs. The shortcut panel is a textContent overlay.
- INV-5: `Escape` always fires, focus or not.
- INV-6: `j`/`k` wrap in both directions.
- INV-7: No new colours. The selected highlight uses the existing palette.

What NOT to do:
- ❌ Browser dialogs (no window dialogs of any kind). Use the inline overlay.
- ❌ innerHTML in the shortcut panel (or anywhere). textContent only
- ❌ New backend endpoints. Ph14 is frontend-only
- ❌ Persist the selected challenge, server-side or in browser storage
- ❌ Suppress `Escape`
- ❌ Send `solved: false`, send the session timer `start` while it runs, or `reset` from a key
- ❌ A second `keydown` listener on `document`. One listener owns every shortcut

Tests (`tests/test_shortcuts.py`, 177 → 187). Same pattern as the other UI tests (TestClient GET `/` and
check the JS in the page). The suite has no headless browser and CI only installs Python:
`test_shortcut_panel_toggle`, `test_escape_closes_panel`, `test_escape_always_fires`,
`test_shortcut_suppressed_in_input`, `test_j_k_navigation_wraps`, `test_s_marks_solved`,
`test_t_starts_stops_timer`, `test_n_focuses_notes`, `test_space_starts_session_timer_only_when_stopped`,
`test_selection_frontend_only`.
