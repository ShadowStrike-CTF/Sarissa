# F14 — Manifest Export Endpoint — Design Doc

| | |
|---|---|
| Brief | M/1.1.15 |
| Tool | Sarissa |
| Version target | v1.10.1 → **v1.11.0** (MINOR — new API endpoint) |
| Status | **DESIGN — awaiting R-approval. Not implemented.** |
| Verified HEAD (main) | `73774dc` (merge of PR #23, v1.10.1 after F02) |
| Test count at HEAD | 276 collected (`pytest --collect-only -q`) |
| Python | `requires-python >=3.11` (cloud recon ran 3.13) |

## 0. Summary

`GET /api/manifest` returns a deterministic, hash-verifiable JSON snapshot of the active session's
challenge set: id, name, category, points, solved, solved_at. It is read-only, needs no auth (loopback +
F02 TrustedHostMiddleware, like every Sarissa route), and never contains a flag.

## 1. Brief corrections (step-1 recon vs the brief)

The brief describes Sarissa as "a CTF challenge management backend" with stored flags and a database.
The repo is a single-user, loopback-only competition dashboard with one JSON session file. These are the
differences recon found. Each row was decided before this doc was written.

| # | Brief says | Repo at 73774dc | Decision |
|---|---|---|---|
| C1 | Challenges store flags; manifest carries `flag_hash` | No challenge field holds a flag. Stored keys: `id, name, category, points, notes, status, created_at, solved_at, challenge_time_seconds, challenge_timer_started_at`. No route accepts a flag | **`flag_hash` dropped.** Nothing is stored, so nothing is exported (Ph9 rule: never fabricate fields). The no-plaintext-flag rule stays as INV-1 and guards the future |
| C2 | "200 always"; "database errors → 500" | No database. With no active session, every session route returns 409 through the app-wide `NoActiveSession` handler | Empty session → **200** with `challenge_count: 0`. **No active session → 409** (same as `/api/export`) |
| C3 | "No authentication, consistent with existing public endpoints" | Sarissa has no auth anywhere. Exposure is limited by binding to 127.0.0.1:7331 and F02 `TrustedHostMiddleware` | No auth. F02 applies unchanged (bad Host → 400) |
| C4 | "PLACEHOLDER confirmed in CLAUDE.md" | CLAUDE.md had no F14 text | This change adds the F14 section to CLAUDE.md |
| C5 | `id`: "uuid or stable integer id" | `uuid.uuid4().hex[:12]`, a 12-char hex string, stable for the challenge's life | `id` is that string |
| C6 | ABC: what status values exist? | Stored `status` ∈ `unsolved`, `in_progress`, `solved` (one-way) | Manifest `solved = (status == "solved")`. `in_progress` maps to `false`. `status` itself is not in the manifest (brief schema). `/api/export` still carries the raw status |
| C7 | `solved_at` ISO 8601 UTC with `Z` | `utc_now()` (`api/session.py`) already emits `YYYY-MM-DDTHH:MM:SSZ`. Set only when status moves to solved, never cleared (one-way) | Pass the stored value through unchanged. No reformatting |
| C8 | Flag hash = plain SHA-256 | Vendored megdan-schema defines flag hashes as salted `hmac-sha256:<hex>` | Moot under C1. If flags are ever stored, use the megdan-schema form and write a new design doc |

## 2. Invariants

- **INV-1: no flag material.** The manifest body, its headers and Sarissa's logs never contain a flag,
  plaintext or hashed. Each manifest challenge is built from an **explicit allowlist** of six keys,
  never by copying or filtering the stored dict. A field added to challenges later (including any
  future flag) cannot reach the manifest without a design change. `notes` is excluded: competitors
  paste flags there.
- **INV-2: deterministic hash.** `manifest_hash` is computed from the ordered `challenges` list alone
  (§6). The same session content always yields the same hash. `exported_at` and `sarissa_version` are
  outside it.
- **INV-3: read-only.** The route never calls `manager.save()`, never writes to a challenge dict, and
  never starts, stops or banks a timer. Same guarantee as `/api/review` and `/api/panels`.
- **INV-4: no fabrication.** Every value comes from stored data (`solved` is derived from stored
  `status`). No defaults are invented.
- **INV-5: `/api/export` unchanged.** Its schema stays `"1.3"`. The manifest is a separate, additional view.
- **INV-6:** port 7331, no external network calls, F02 middleware untouched, existing 276 tests stay green.

## 3. Endpoint

`GET /api/manifest`, no request body, no auth.

**200** `Content-Type: application/json`, inline. There is no `Content-Disposition` (the brief asks for a
JSON response, not a download; `/api/export` is the download route).

```json
{
  "sarissa_version": "1.11.0",
  "exported_at": "2026-11-07T12:40:00Z",
  "challenge_count": 2,
  "manifest_hash": "15567ddbf7d345e3d1190497e7a09606ba52423aa1ee0fa092f484630670e03d",
  "challenges": [
    {"id": "a1b2c3d4e5f6", "name": "Disk image", "category": "Forensics", "points": 100,
     "solved": true, "solved_at": "2026-11-07T12:34:56Z"},
    {"id": "0f9e8d7c6b5a", "name": "Ransom note", "category": "Forensics", "points": 0,
     "solved": false, "solved_at": null}
  ]
}
```

| Field | Type | Source |
|---|---|---|
| `sarissa_version` | str | `sarissa.__version__` (§9) |
| `exported_at` | str | `session.utc_now()` at request time (`…Z`) |
| `challenge_count` | int | `len(challenges)` |
| `manifest_hash` | str, 64 lowercase hex | §6 |
| `challenges[].id` | str | stored `id` |
| `challenges[].name` | str | stored `name` |
| `challenges[].category` | str | stored `category`; `""` when unset (no "Uncategorised" mapping, which is a review-only display label) |
| `challenges[].points` | int ≥ 0 | stored `points`; `0` = unset (Ph11 INV-3) |
| `challenges[].solved` | bool | `status == "solved"` |
| `challenges[].solved_at` | str \| null | stored `solved_at`: non-null if and only if solved |

**Errors**
- **409** `{"detail": "No active session"}`: no active session (existing app-wide handler).
- **400**: Host header not 127.0.0.1/localhost (F02, before routing).
- **500**: unexpected exception. FastAPI/Starlette's default 500 already returns a plain body with no
  stack trace (debug is off). **R decision (optional):** add a route-local `try/except` returning
  `JSONResponse({"error": "internal server error"}, 500)` to match the brief's exact body. Recommended:
  no. Sarissa has no other route-specific 500 handler, and nothing here can realistically raise.
- No 404 and no error for an empty session: 200, `challenge_count: 0`, `challenges: []`.

## 4. Flag security

Sarissa stores no flags (C1), so the manifest has no flag field of any kind. INV-1's allowlist
construction is the enforcement: `build_manifest` names its six output keys literally. The route logs
nothing about challenge content (Sarissa's only logger is `sarissa.plugins`). Test T5 plants a flag-shaped
string in `notes` and asserts it is absent from the response bytes and headers.

## 5. Ordering

Sort key: `(category, name, id)`, ascending, using Python's default `str` ordering (case-sensitive,
by code point). The categories route (`compute_categories`) uses the same ordering.

- `""` (uncategorised) sorts before every non-empty category.
- `"Zeta"` sorts before `"alpha"` (uppercase before lowercase). No case folding, so the order is exactly
  reproducible in any language.
- **`id` breaks ties.** Sarissa allows duplicate names in a category. Without a third key the order of
  duplicates would follow creation order, which a consumer cannot reproduce from the manifest.

## 6. `manifest_hash` algorithm

```python
canonical = json.dumps(challenges, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
manifest_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

- `challenges` is the final, ordered list exactly as it appears in the response (§5).
- `ensure_ascii=True` is Python's default but is pinned explicitly, because it changes the bytes for any
  non-ASCII name (`é` → `é`). Consumers in other languages must emit the same escaping.
- `sort_keys` orders the keys inside each object. It does not reorder the list.
- Worked examples (computed with the recipe above):
  - `[]` → `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`
  - the two-challenge list in §3 → `15567ddbf7d345e3d1190497e7a09606ba52423aa1ee0fa092f484630670e03d`
- A consumer verifies by re-running the recipe on the received `challenges` array, without reordering.

## 7. Zapis Ph6 compatibility (⚠️ ABC flag — open)

- The Zapis Ph6 doc (`Zapis_Ph6_Digger_Prompt_v1_0.md`, DocLibrary) and the Zapis repo are **not
  available in this session**, so the field check could not be done against the authoritative consumer spec.
- What CLAUDE.md records (F01, Zapis 1.3.0): Zapis imports **`/api/export`**. It accepts
  `schema_version` `"1.0"`/`"1.3"`, compares `tool` case-insensitively, and reads `session.name`,
  `challenges[].name` and `challenges[].notes`.
- The brief's expected manifest fields (`name`, `solved`, `solved_at`, `points`, `category`) are all
  present, with exactly those names. There is no `title` or `score`.
- **Mismatch:** the manifest has no `schema_version`, `tool`, `session` or `notes`. The current Zapis
  importer cannot ingest it as-is. Options for the Zapis side:
  1. Zapis keeps importing `/api/export` (works today) and uses the manifest only for integrity checks.
  2. Zapis gains a separate manifest importer keyed on the presence of `manifest_hash`.

  Per the brief, the Sarissa schema wins. Any change lands in the Zapis Ph6 doc.
- **`solved_at` parsing:** `datetime.fromisoformat("2026-11-07T12:34:56Z")` works on Python ≥ 3.11.
  `date.fromisoformat()` **raises** on it. Zapis must use `datetime.fromisoformat(v).date()` or `v[:10]`.
- **Status:** Zapis's Ph3 fixture uses `"status": "in_progress"`. That is a real Sarissa value (C6), but
  the manifest carries `solved` (bool) instead of `status`. `in_progress` and `unsolved` both arrive as
  `solved: false`. Zapis needs `/api/export` if it wants the three-way status.

## 8. Empty-state behaviour

Active session with no challenges → 200:
`{"sarissa_version": "1.11.0", "exported_at": "…Z", "challenge_count": 0, "manifest_hash": "4f53cd…b945", "challenges": []}`.
No active session → 409 (C2).

## 9. Implementation sketch (for Digger)

- `src/sarissa/__init__.py`: add `__version__ = "1.11.0"`, the single runtime source. A test asserts it
  equals `pyproject.toml`'s `version`. `importlib.metadata.version("sarissa")` is avoided on purpose:
  in the PyInstaller exe it needs `copy_metadata` in the spec, or it raises.
- `src/sarissa/main.py`: a pure `build_manifest(data) -> dict` next to `build_export()`:
  allowlisted six-key dicts → sort `(category, name, id)` → hash → envelope. Plus
  `@app.get("/api/manifest")` in `create_app()`, which calls `manager.require_current()` (raises
  `NoActiveSession` → 409) and returns `build_manifest(data)`.
- No new dependencies (`json`, `hashlib` stdlib). No frontend change in v1.11.0 (API only; R may ask
  for a header button later). Export schema stays `"1.3"`.
- `pyproject.toml` version → 1.11.0. Add a short F14 section to CLAUDE.md marking it implemented.

## 10. Test plan (`tests/test_manifest.py`)

Fixtures follow `tests/test_export.py` / `tests/test_review.py` (tmp `sessions_dir`, TestClient with the
conftest `http://127.0.0.1` base_url).

| # | Test | Asserts |
|---|---|---|
| T1 | `test_manifest_shape` | 200, `application/json`; top-level keys exactly the five; each challenge's keys exactly the six |
| T2 | `test_manifest_ordering` | category ASC then name ASC, `""` first, case-sensitive; duplicate (category, name) ordered by `id` |
| T3 | `test_manifest_hash_reproducible` | re-running the §6 recipe on the body's `challenges` equals `manifest_hash`; two calls give the same hash even though `exported_at` differs |
| T4 | `test_manifest_solved_at` | unsolved and in_progress → `solved: false`, `solved_at: null`; solved → `true` + stored `…Z` value (parses with `datetime.fromisoformat`) |
| T5 | `test_manifest_no_plaintext_flag` | a challenge whose notes hold `flag{s3cr3t}` → that string is absent from the response bytes and headers; no `notes`/`flag*` key |
| T6 | `test_manifest_empty_session` | 200, `challenge_count == 0`, `challenges == []`, hash = `4f53cd…b945` |
| T7 | `test_manifest_409_no_session` | 409 |
| T8 | `test_manifest_read_only` | session file bytes and in-memory challenge dicts unchanged; a running challenge timer is still running with the same `started_at` |
| T9 | `test_manifest_version` | `sarissa_version == sarissa.__version__ ==` pyproject version |
| T10 | `test_manifest_trusted_host` | `Host: evil.example` → 400 |
| T11 | `test_export_unchanged` | `/api/export` still `schema_version == "1.3"` |

Zapis import roundtrip: **out of scope**. Zapis is not in this repo, and its importer currently targets
`/api/export` (§7). Expected count: 276 → 287.

## 11. Version bump

v1.10.1 → **v1.11.0** (MINOR: new endpoint, no breaking change). No tag pushed.

## 12. Digger prompt block (revised to match this doc)

```
# F14 — Manifest Export Endpoint
# Repo: ShadowStrike-CTF/sarissa
# Target version: v1.11.0

Present your plan and STOP. Do not write any code until I reply with approval.

## Context
Sarissa is a loopback-only CTF competition dashboard (FastAPI on 127.0.0.1:7331, one JSON session
file per competition). F14 adds GET /api/manifest — a deterministic, hash-verifiable JSON snapshot of
the active session's challenge set. Implement per docs/F14_manifest_design.md.

## Expected HEAD (main)
73774dc (v1.10.1) or later — verify before starting.

## Constraints (all locked)
- GET /api/manifest, no auth (F02 TrustedHostMiddleware unchanged), application/json, inline
- Top-level: sarissa_version, exported_at, challenge_count, manifest_hash, challenges
- Per challenge (explicit allowlist, never copy the stored dict): id, name, category, points, solved, solved_at
- NO flag field of any kind. Sarissa stores no flags. Never include notes. Nothing flag-related in headers or logs
- solved = status == "solved"; solved_at = stored value (already ISO 8601 UTC with Z), null unless solved
- Ordering: (category, name, id) ascending, plain Python str ordering
- manifest_hash = sha256(json.dumps(challenges, sort_keys=True, separators=(",",":"), ensure_ascii=True).encode("utf-8")).hexdigest()
- Active session with no challenges → 200 count 0; no active session → 409 (existing handler)
- Read-only: never manager.save(), never mutate challenges or timers
- __version__ in src/sarissa/__init__.py; pyproject → 1.11.0; /api/export schema stays "1.3"
- Path-scoped git adds only. No tag.

## Step 1 recon
Report actual HEAD, branch list, test count from main, Python version, current challenge model fields.

## Commit message template
feat(sarissa): F14 — manifest export endpoint

- GET /api/manifest: deterministic challenge-set snapshot
- No flag fields (Sarissa stores none); explicit six-key allowlist
- manifest_hash: SHA-256 of canonical JSON (sort_keys, no whitespace, ensure_ascii)
- solved_at: stored ISO 8601 UTC (Z), null unless solved
- Ordering: category, name, id ascending
- 409 with no active session; 200 with empty session
- Version: 1.11.0
- Tests: N green
```

© 2026 ShadowStrike. All rights reserved.
