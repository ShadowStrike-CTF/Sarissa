"""Challenge IDs (``MGD-{SET}-{NN}``), set IDs and point-of-entry IDs (``POE-{SET}-{nnnn}``)."""

from __future__ import annotations

import re
from typing import Annotated, NamedTuple

from pydantic import StringConstraints

SET_ID_PATTERN = r"[A-Z0-9]{4,12}"
CHALLENGE_ID_PATTERN = rf"^MGD-({SET_ID_PATTERN})-(0[1-9]|[1-9][0-9])$"
POE_ID_PATTERN = rf"^POE-({SET_ID_PATTERN})-(000[1-9]|00[1-9][0-9]|0[1-9][0-9]{{2}}|[1-9][0-9]{{3}})$"

_SET_RE = re.compile(rf"^{SET_ID_PATTERN}$")
_CHALLENGE_RE = re.compile(CHALLENGE_ID_PATTERN)
_POE_RE = re.compile(POE_ID_PATTERN)

SetId = Annotated[str, StringConstraints(pattern=rf"^{SET_ID_PATTERN}$")]
ChallengeId = Annotated[str, StringConstraints(pattern=CHALLENGE_ID_PATTERN)]
PoeId = Annotated[str, StringConstraints(pattern=POE_ID_PATTERN)]


class ChallengeIdParts(NamedTuple):
    set_id: str
    number: int


class PoeIdParts(NamedTuple):
    set_id: str
    number: int


def is_valid_set_id(value: object) -> bool:
    return isinstance(value, str) and _SET_RE.fullmatch(value) is not None


def is_valid_challenge_id(value: object) -> bool:
    return isinstance(value, str) and _CHALLENGE_RE.fullmatch(value) is not None


def is_valid_poe_id(value: object) -> bool:
    return isinstance(value, str) and _POE_RE.fullmatch(value) is not None


def _check_number(number: object, low: int, high: int) -> int:
    if isinstance(number, bool) or not isinstance(number, int):
        raise TypeError(f"number must be an int, got {type(number).__name__}")
    if not low <= number <= high:
        raise ValueError(f"number must be {low}-{high}, got {number}")
    return number


def _check_set(set_id: object) -> str:
    if not is_valid_set_id(set_id):
        raise ValueError(f"invalid set id {set_id!r}: expected [A-Z0-9]{{4,12}}")
    return set_id  # type: ignore[return-value]


def parse_challenge_id(value: str) -> ChallengeIdParts:
    """``"MGD-ABCD-07"`` -> ``ChallengeIdParts("ABCD", 7)``. Raises ``ValueError`` if invalid."""
    m = _CHALLENGE_RE.fullmatch(value) if isinstance(value, str) else None
    if m is None:
        raise ValueError(f"invalid challenge id {value!r}: expected MGD-{{SET}}-{{01..99}}")
    return ChallengeIdParts(m.group(1), int(m.group(2)))


def format_challenge_id(set_id: str, number: int) -> str:
    """``("ABCD", 7)`` -> ``"MGD-ABCD-07"``."""
    return f"MGD-{_check_set(set_id)}-{_check_number(number, 1, 99):02d}"


def parse_poe_id(value: str) -> PoeIdParts:
    """``"POE-ABCD-0042"`` -> ``PoeIdParts("ABCD", 42)``. Raises ``ValueError`` if invalid."""
    m = _POE_RE.fullmatch(value) if isinstance(value, str) else None
    if m is None:
        raise ValueError(f"invalid PoE id {value!r}: expected POE-{{SET}}-{{0001..9999}}")
    return PoeIdParts(m.group(1), int(m.group(2)))


def format_poe_id(set_id: str, number: int) -> str:
    """``("ABCD", 42)`` -> ``"POE-ABCD-0042"``."""
    return f"POE-{_check_set(set_id)}-{_check_number(number, 1, 9999):04d}"
