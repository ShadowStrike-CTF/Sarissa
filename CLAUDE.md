# Sarissa — CTF Dashboard
Rapid-access CTF dashboard for digital forensics competitions.
by ShadowStrike. MIT.

## Tech stack
- Python 3.11
- FastAPI + uvicorn (backend, port 7331 ALWAYS — no dynamic port)
- Vanilla HTML/CSS/JS single-file frontend
- python-magic (magic byte detection — python-magic-bin required on Windows)
- hashlib stdlib (MD5/SHA1/SHA256/SHA512)
- json stdlib (session storage at ~/.sarissa/sessions/<name>.json)
- PyInstaller (Windows primary)

## Architecture
Named sessions per competition. Auto-save every 60 seconds.
Four DF quick tools: hash calculator, timestamp converter, file type inspector,
string extractor. All four always visible — no navigation required.
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
