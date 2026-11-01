"""Pure invariant checks that hosts run on plugin output.

Each check returns a list; an empty list means the invariant holds. Malformed plugin output
is reported, not raised. Only bad host-supplied arguments (such as an empty flag) raise.

    INV-P1  check_no_plaintext_flag   no plaintext flag in shipped artefacts
    INV-P2  check_answer_provenance   answers derive from cited PoE records
    INV-P3  check_no_answer_fields    solver-side items carry flag_hash only
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

MIN_INNER_LENGTH = 4
"""Inner flag values shorter than this are not searched on their own (too noisy)."""

ENCODINGS: tuple[str, ...] = ("utf-8", "utf-16-le")

FORBIDDEN_SOLVER_KEYS = frozenset({"raw_value", "normalised_value", "how_to_find"})
FORBIDDEN_SOLVER_SUBSTRINGS: tuple[str, ...] = ("answer", "solution", "flag")
ALLOWED_SOLVER_KEYS = frozenset({"flag_hash"})


class PlaintextHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    blob: str
    needle: Literal["flag", "inner"]
    encoding: str
    offset: int


class Problem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    location: str
    message: str


# --- INV-P1 ---------------------------------------------------------------------------


def _inner_value(flag: str) -> str | None:
    start, end = flag.find("{"), flag.rfind("}")
    if start == -1 or end <= start + 1:
        return None
    return flag[start + 1 : end]


def _find_all(haystack: bytes, needle: bytes) -> list[int]:
    offsets, i = [], haystack.find(needle)
    while i != -1:
        offsets.append(i)
        i = haystack.find(needle, i + 1)
    return offsets


def check_no_plaintext_flag(blobs: Mapping[str, bytes], flag: str) -> list[PlaintextHit]:
    """Find the flag (and its inner value) in any blob, as UTF-8 or UTF-16LE, ignoring ASCII case.

    The inner value is the text between the first ``{`` and the last ``}``. It is searched only
    if it has at least :data:`MIN_INNER_LENGTH` characters, and inner hits that sit inside a
    full-flag hit are not reported twice.
    """
    if not isinstance(flag, str) or not flag:
        raise ValueError("flag must be a non-empty str")
    inner = _inner_value(flag)
    if inner is not None and len(inner) < MIN_INNER_LENGTH:
        inner = None

    hits: list[PlaintextHit] = []
    for name, blob in blobs.items():
        hay = bytes(blob).lower()
        for enc in ENCODINGS:
            full = flag.encode(enc).lower()
            full_offsets = _find_all(hay, full)
            hits.extend(
                PlaintextHit(blob=name, needle="flag", encoding=enc, offset=o) for o in full_offsets
            )
            if inner is None:
                continue
            needle = inner.encode(enc).lower()
            for o in _find_all(hay, needle):
                inside = any(f <= o and o + len(needle) <= f + len(full) for f in full_offsets)
                if not inside:
                    hits.append(PlaintextHit(blob=name, needle="inner", encoding=enc, offset=o))
    return hits


# --- INV-P2 ---------------------------------------------------------------------------


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _index_inventory(inventory: Iterable[Any] | Mapping[str, Any]) -> dict[str, Any]:
    records = inventory.values() if isinstance(inventory, Mapping) else inventory
    index: dict[str, Any] = {}
    for record in records:
        poe_id = _get(record, "poe_id")
        if isinstance(poe_id, str):
            index[poe_id] = record
    return index


def check_answer_provenance(
    item: Any, inventory: Iterable[Any] | Mapping[str, Any]
) -> list[Problem]:
    """Every answer must equal the ``raw_value`` or ``normalised_value`` of a PoE record the
    item cites in ``poe_refs``.

    ``item`` is a :class:`~megdan_schema.plugin.ChallengeItem` or a dict. ``inventory`` is an
    iterable of PoE records (models or dicts), or a dict of them keyed by ``poe_id``.
    """
    problems: list[Problem] = []
    answers = _get(item, "answers")
    refs = _get(item, "poe_refs")

    if not isinstance(answers, (list, tuple)) or not answers:
        problems.append(Problem(code="no_answers", location="/answers", message="item has no answers"))
        answers = []
    if not isinstance(refs, (list, tuple)) or not refs:
        problems.append(
            Problem(code="no_citations", location="/poe_refs", message="item cites no PoE records")
        )
        refs = []

    index = _index_inventory(inventory)
    allowed: set[Any] = set()
    for i, ref in enumerate(refs):
        record = index.get(ref) if isinstance(ref, str) else None
        if record is None:
            problems.append(
                Problem(
                    code="unknown_poe",
                    location=f"/poe_refs/{i}",
                    message=f"cited PoE record {ref!r} is not in the inventory",
                )
            )
            continue
        allowed.add(_get(record, "raw_value"))
        allowed.add(_get(record, "normalised_value"))
    allowed.discard(None)

    for i, answer in enumerate(answers):
        if not isinstance(answer, str) or answer not in allowed:
            problems.append(
                Problem(
                    code="answer_not_in_cited_poe",
                    location=f"/answers/{i}",
                    message="answer does not match the raw or normalised value of any cited PoE record",
                )
            )
    return problems


# --- INV-P3 ---------------------------------------------------------------------------


def _is_forbidden_key(key: str) -> bool:
    k = key.lower()
    if k in ALLOWED_SOLVER_KEYS:
        return False
    return (
        k in FORBIDDEN_SOLVER_KEYS
        or any(s in k for s in FORBIDDEN_SOLVER_SUBSTRINGS)
        or k.endswith("path")
    )


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _walk(node: Any, location: str, problems: list[Problem]) -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            key_s = str(key)
            here = f"{location}/{_escape(key_s)}"
            if _is_forbidden_key(key_s):
                problems.append(
                    Problem(
                        code="forbidden_field",
                        location=here,
                        message=f"solver-side item must not carry {key_s!r}; only flag_hash is allowed",
                    )
                )
            _walk(value, here, problems)
    elif isinstance(node, (list, tuple)):
        for i, value in enumerate(node):
            _walk(value, f"{location}/{i}", problems)


def check_no_answer_fields(item_for_solver: Any) -> list[Problem]:
    """No answer, solution, flag or path fields anywhere in a solver-side item (only ``flag_hash``).

    Accepts a pydantic model, a dict, or a list of them; walks nested dicts and lists.
    Locations are JSON-pointer style (``/hints/0/answer``).
    """
    if isinstance(item_for_solver, BaseModel):
        item_for_solver = item_for_solver.model_dump(mode="json")
    problems: list[Problem] = []
    _walk(item_for_solver, "", problems)
    return problems
