# Sarissa — four DF quick tools: hash, timestamp, file type, strings.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

"""Digital forensics quick tools.

Upload endpoints take the raw request body, so no file name ever reaches the
server — file type comes from magic bytes alone.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Literal

import magic
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

# --- Hash calculator --------------------------------------------------------

HASH_ALGORITHMS = ("md5", "sha1", "sha256", "sha512")


def _new_hashers() -> dict[str, Any]:
    return {
        "md5": hashlib.md5(usedforsecurity=False),
        "sha1": hashlib.sha1(usedforsecurity=False),
        "sha256": hashlib.sha256(),
        "sha512": hashlib.sha512(),
    }


def compute_hashes(data: bytes) -> dict[str, str]:
    """Always returns all four digests together — never a partial set."""
    hashers = _new_hashers()
    for h in hashers.values():
        h.update(data)
    return {name: hashers[name].hexdigest() for name in HASH_ALGORITHMS}


# --- File type inspector ----------------------------------------------------

MAGIC_HEADER_BYTES = 65536  # enough for deep signatures (tar @257, ISO9660 @32769)


def detect_file_type(data: bytes) -> dict[str, Any]:
    """Identify content by magic bytes only. Deliberately takes no file name."""
    header = data[:MAGIC_HEADER_BYTES]
    return {
        "mime": magic.from_buffer(header, mime=True),
        "description": magic.from_buffer(header),
        "magic_hex": data[:16].hex(" "),
        "size": len(data),
    }


# --- String extractor -------------------------------------------------------

DEFAULT_MIN_STRINGS = 4
MAX_STRINGS = 20_000
_min_strings = DEFAULT_MIN_STRINGS


def set_min_strings(n: int) -> None:
    """Set by the --min-strings CLI flag only. Never exposed to the web UI."""
    global _min_strings
    if n < 1:
        raise ValueError("--min-strings must be at least 1")
    _min_strings = n


def get_min_strings() -> int:
    return _min_strings


@lru_cache(maxsize=16)
def _patterns(n: int) -> tuple[re.Pattern[bytes], re.Pattern[bytes]]:
    ascii_re = re.compile(rb"[\x20-\x7e\t]{%d,}" % n)
    utf16_re = re.compile(rb"(?:[\x20-\x7e\t]\x00){%d,}" % n)
    return ascii_re, utf16_re


def extract_strings(data: bytes, min_length: int | None = None, limit: int = MAX_STRINGS) -> dict[str, Any]:
    """Printable ASCII and UTF-16LE runs of at least `min_length` characters."""
    n = min_length if min_length is not None else _min_strings
    ascii_re, utf16_re = _patterns(n)
    found = [
        {"offset": m.start(), "encoding": "ascii", "value": m.group().decode("ascii")}
        for m in ascii_re.finditer(data)
    ]
    found += [
        {"offset": m.start(), "encoding": "utf-16le", "value": m.group().decode("utf-16-le")}
        for m in utf16_re.finditer(data)
    ]
    found.sort(key=lambda s: s["offset"])
    return {"count": len(found), "truncated": len(found) > limit, "strings": found[:limit]}


# --- Timestamp converter ----------------------------------------------------

TimestampFormat = Literal["unix", "unix_ms", "filetime", "webkit", "cocoa", "hfs", "iso"]

_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_US = 1_000_000
_EPOCH_1601_S = 11_644_473_600  # seconds from 1601-01-01 to 1970-01-01
_EPOCH_2001_S = 978_307_200  # Cocoa / Apple absolute time
_EPOCH_1904_S = -2_082_844_800  # HFS+


def _to_unix_us(value: str, fmt: str) -> int:
    """Convert input to integer microseconds since the Unix epoch (UTC)."""
    if fmt == "iso":
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = dt - _UNIX_EPOCH
        return (delta.days * 86_400 + delta.seconds) * _US + delta.microseconds
    try:
        num = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Not a number: {value!r}") from exc
    if not num.is_finite():
        raise ValueError(f"Not a finite number: {value!r}")
    if fmt == "unix":
        return int(num * _US)
    if fmt == "unix_ms":
        return int(num * 1000)
    if fmt == "filetime":  # 100 ns ticks since 1601
        return int(num / 10) - _EPOCH_1601_S * _US
    if fmt == "webkit":  # µs since 1601 (Chrome / WebKit)
        return int(num) - _EPOCH_1601_S * _US
    if fmt == "cocoa":
        return int(num * _US) + _EPOCH_2001_S * _US
    if fmt == "hfs":
        return int(num * _US) + _EPOCH_1904_S * _US
    raise ValueError(f"Unknown format {fmt!r}")


def _seconds(us: int) -> int | float:
    q, r = divmod(us, _US)
    return q if r == 0 else us / _US


def convert_timestamp(value: str, fmt: str = "unix") -> dict[str, Any]:
    """Convert one timestamp into every supported representation (UTC)."""
    us = _to_unix_us(value.strip(), fmt)
    try:
        dt = _UNIX_EPOCH + timedelta(microseconds=us)
    except OverflowError as exc:
        raise ValueError("Timestamp out of range (years 1-9999)") from exc
    return {
        "iso": dt.isoformat().replace("+00:00", "Z"),
        "human": dt.strftime("%a %d %b %Y %H:%M:%S UTC"),
        "unix": _seconds(us),
        "unix_ms": us // 1000,
        "filetime": (us + _EPOCH_1601_S * _US) * 10,
        "webkit": us + _EPOCH_1601_S * _US,
        "cocoa": _seconds(us - _EPOCH_2001_S * _US),
        "hfs": _seconds(us - _EPOCH_1904_S * _US),
    }


# --- API -------------------------------------------------------------------

router = APIRouter(prefix="/api/tools", tags=["tools"])


class TimestampRequest(BaseModel):
    value: str = Field(min_length=1, max_length=64)
    format: TimestampFormat = "unix"


@router.post("/hash")
async def hash_body(request: Request) -> dict[str, Any]:
    hashers = _new_hashers()
    size = 0
    async for chunk in request.stream():  # streamed: evidence files can be large
        size += len(chunk)
        for h in hashers.values():
            h.update(chunk)
    return {**{name: hashers[name].hexdigest() for name in HASH_ALGORITHMS}, "size": size}


@router.post("/filetype")
async def filetype_body(request: Request) -> dict[str, Any]:
    return detect_file_type(await request.body())


@router.post("/strings")
async def strings_body(request: Request) -> dict[str, Any]:
    # No min-length parameter: the UI default is fixed; only the CLI can change it.
    return extract_strings(await request.body())


@router.post("/timestamp")
def timestamp(body: TimestampRequest) -> dict[str, Any]:
    try:
        return convert_timestamp(body.value, body.format)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
