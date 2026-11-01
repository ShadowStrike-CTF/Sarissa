# Sarissa — v1.9.0 vendored megdan-schema is byte-for-byte the pinned tag.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import hashlib
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "src" / "sarissa" / "_vendor"
PKG = VENDOR / "megdan_schema"
MANIFEST = PKG / "VENDORED.txt"


def pinned() -> dict[str, str]:
    """`{"megdan_schema/x.py": "<hex>"}` from the sha256sum-format lines of VENDORED.txt."""
    out = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and ":" not in line.split()[0]:
            digest, rel = line.split("  ", 1)
            out[rel] = digest
    return out


def on_disk() -> set[str]:
    return {
        p.relative_to(VENDOR).as_posix()
        for p in PKG.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"} and p != MANIFEST
    }


def test_vendored_header_pins_tag_and_commit():
    text = MANIFEST.read_text(encoding="utf-8")
    assert "source: https://github.com/ShadowStrike-CTF/megdan-schema" in text
    assert "tag: v0.1.0" in text
    assert "commit: b0f182cc807844f875085d95cce2e56562fdfad3" in text


def test_vendored_hashes_match():
    pins = pinned()
    assert len(pins) == 11
    for rel, digest in pins.items():
        assert hashlib.sha256((VENDOR / rel).read_bytes()).hexdigest() == digest, rel


def test_vendored_file_set_exact():
    assert on_disk() == set(pinned())


def test_vendored_contract_version():
    from sarissa._vendor.megdan_schema import __version__
    from sarissa._vendor.megdan_schema.plugin import ENTRY_POINT_GROUPS, PLUGIN_API, Slot

    assert __version__ == "0.1.0"
    assert PLUGIN_API == "1.0"
    assert ENTRY_POINT_GROUPS[Slot.PANEL] == "megdan.sarissa.panels"
