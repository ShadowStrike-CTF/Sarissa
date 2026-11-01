"""Write JSON Schema for every model to ``schemas/``.

    python -m megdan_schema.export            # write schemas/*.json
    python -m megdan_schema.export --check    # exit 1 if schemas/ is out of date
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from .manifest import SetManifest
from .plugin import (
    ChallengeItem,
    PanelData,
    PluginDescription,
    ScoreResult,
    SolverChallengeItem,
)
from .poe import PoERecord

MODELS: dict[str, type[BaseModel]] = {
    "set_manifest": SetManifest,
    "poe_record": PoERecord,
    "challenge_item": ChallengeItem,
    "solver_challenge_item": SolverChallengeItem,
    "score_result": ScoreResult,
    "panel_data": PanelData,
    "plugin_description": PluginDescription,
}

DEFAULT_DIR = Path("schemas")


def render_schemas() -> dict[str, str]:
    """``{"set_manifest.json": "<json text>", ...}``. Deterministic output."""
    return {
        f"{name}.json": json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        for name, model in MODELS.items()
    }


def write_schemas(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, text in render_schemas().items():
        path = out_dir / filename
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written


def stale_schemas(out_dir: Path) -> list[str]:
    """Filenames in ``out_dir`` that are missing or differ from the current models."""
    stale = []
    for filename, text in render_schemas().items():
        path = out_dir / filename
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            stale.append(filename)
    return stale


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m megdan_schema.export", description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_DIR, help="output directory (default: schemas)")
    parser.add_argument("--check", action="store_true", help="exit 1 if the schemas are out of date")
    args = parser.parse_args(argv)

    if args.check:
        stale = stale_schemas(args.out)
        for filename in stale:
            print(f"out of date: {args.out / filename}")
        if stale:
            print("run: python -m megdan_schema.export")
            return 1
        print(f"schemas up to date ({len(MODELS)} files)")
        return 0

    for path in write_schemas(args.out):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via main() in tests
    raise SystemExit(main())
