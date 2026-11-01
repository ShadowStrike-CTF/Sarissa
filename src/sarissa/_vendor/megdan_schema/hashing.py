"""Algorithm-prefixed hash strings and flag hashing.

Only ``"sha256:{hex}"`` and ``"hmac-sha256:{hex}"`` (64 lowercase hex chars) are valid.
Bare hex is rejected so a hash always says how it was made.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Annotated, NamedTuple

from pydantic import StringConstraints

SHA256_PREFIX = "sha256:"
HMAC_SHA256_PREFIX = "hmac-sha256:"

HASH_STRING_PATTERN = r"^(sha256|hmac-sha256):([0-9a-f]{64})$"
SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
FLAG_HASH_PATTERN = r"^hmac-sha256:[0-9a-f]{64}$"

_HASH_RE = re.compile(HASH_STRING_PATTERN)

HashString = Annotated[str, StringConstraints(pattern=HASH_STRING_PATTERN)]
"""Either ``sha256:`` or ``hmac-sha256:`` prefixed."""
Sha256Hash = Annotated[str, StringConstraints(pattern=SHA256_PATTERN)]
"""A plain content hash: ``sha256:`` only."""
FlagHash = Annotated[str, StringConstraints(pattern=FLAG_HASH_PATTERN)]
"""A salted flag hash: ``hmac-sha256:`` only."""


class ParsedHash(NamedTuple):
    algorithm: str
    hex: str


def is_hash_string(value: object) -> bool:
    return isinstance(value, str) and _HASH_RE.fullmatch(value) is not None


def parse_hash(value: str) -> ParsedHash:
    """``"sha256:ab…"`` -> ``ParsedHash("sha256", "ab…")``. Raises ``ValueError`` on bare or bad hex."""
    m = _HASH_RE.fullmatch(value) if isinstance(value, str) else None
    if m is None:
        raise ValueError(
            f"invalid hash string {value!r}: expected 'sha256:<64 hex>' or 'hmac-sha256:<64 hex>'"
        )
    return ParsedHash(m.group(1), m.group(2))


def sha256_str(data: bytes) -> str:
    """SHA-256 of ``data`` as ``"sha256:{hex}"``."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"data must be bytes-like, got {type(data).__name__}")
    return SHA256_PREFIX + hashlib.sha256(data).hexdigest()


def _salt_bytes(salt: str | bytes) -> bytes:
    if isinstance(salt, str):
        salt = salt.encode("utf-8")
    elif not isinstance(salt, (bytes, bytearray)):
        raise TypeError(f"salt must be str or bytes, got {type(salt).__name__}")
    if not salt:
        raise ValueError("salt must not be empty")
    return bytes(salt)


def _hmac_hex(flag: str, salt: str | bytes) -> str:
    if not isinstance(flag, str):
        raise TypeError(f"flag must be str, got {type(flag).__name__}")
    return hmac.new(_salt_bytes(salt), flag.encode("utf-8"), hashlib.sha256).hexdigest()


def flag_hash(flag: str, salt: str | bytes) -> str:
    """HMAC-SHA256 (key = salt, message = UTF-8 flag) as ``"hmac-sha256:{hex}"``."""
    return HMAC_SHA256_PREFIX + _hmac_hex(flag, salt)


def verify_flag(submission: str, flag_hash: str, salt: str | bytes) -> bool:
    """True if ``submission`` hashes to ``flag_hash`` under ``salt``. Constant-time compare.

    The submission is compared exactly as given; trimming or case rules are the host's job.
    Raises ``ValueError`` if ``flag_hash`` is not a well-formed ``hmac-sha256:`` string.
    """
    parsed = parse_hash(flag_hash)
    if parsed.algorithm != "hmac-sha256":
        raise ValueError("flag_hash must use the 'hmac-sha256:' prefix")
    return hmac.compare_digest(_hmac_hex(submission, salt), parsed.hex)
