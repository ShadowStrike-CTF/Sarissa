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
