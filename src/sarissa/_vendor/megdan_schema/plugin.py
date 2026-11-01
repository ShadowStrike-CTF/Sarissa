"""Plugin contract (Megdan Plugin Interface Spec v0.1.1).

Every plugin object exposes ``PLUGIN_API``, ``NAME``, ``VERSION`` and ``describe()``, plus
one slot callable:

    scenario provider: provide(context: dict, inventory: list[dict]) -> list[dict]
    scorer:            score(item: dict, submission: dict) -> dict      # ScoreResult
    panel:             panel(session_export: dict) -> dict              # PanelData

Hosts discover plugins with ``importlib.metadata.entry_points(group=...)`` using the groups
in :data:`ENTRY_POINT_GROUPS`, and validate everything a plugin returns against the models
here before using it.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from .hashing import FlagHash
from .ids import ChallengeId, PoeId

PLUGIN_API = "1.0"
"""Version of the plugin contract this package describes. Hosts accept the same major."""

PLUGIN_NAME_PATTERN = r"^[a-z0-9_-]+$"
API_VERSION_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?$"
_API_RE = re.compile(API_VERSION_PATTERN)

PluginName = Annotated[str, StringConstraints(pattern=PLUGIN_NAME_PATTERN)]
ApiVersion = Annotated[str, StringConstraints(pattern=API_VERSION_PATTERN)]


class Slot(StrEnum):
    SCENARIO_PROVIDER = "scenario_provider"
    SCORER = "scorer"
    PANEL = "panel"


ENTRY_POINT_GROUPS: dict[Slot, str] = {
    Slot.SCENARIO_PROVIDER: "megdan.poligon.scenario_providers",
    Slot.SCORER: "megdan.poligon.scorers",
    Slot.PANEL: "megdan.sarissa.panels",
}

SLOT_CALLABLES: dict[Slot, str] = {
    Slot.SCENARIO_PROVIDER: "provide",
    Slot.SCORER: "score",
    Slot.PANEL: "panel",
}

REQUIRED_PLUGIN_ATTRIBUTES: tuple[str, ...] = ("PLUGIN_API", "NAME", "VERSION", "describe")


class PluginDescription(BaseModel):
    """What ``describe()`` returns: ``{"name", "version", "api", "slot"}``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: PluginName
    version: str = Field(min_length=1)
    api: ApiVersion
    slot: Slot


class ChallengeItem(BaseModel):
    """A challenge item on the setter side (what a scenario provider returns).

    ``answers`` and ``poe_refs`` never leave the setter side; use :func:`to_solver_item`
    before an item crosses to Sarissa.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    challenge_id: ChallengeId
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    points: StrictInt = Field(ge=0)
    flag_hash: FlagHash
    answers: list[StrictStr] = Field(min_length=1)
    poe_refs: list[PoeId] = Field(min_length=1)


class SolverChallengeItem(BaseModel):
    """A challenge item as the solver side sees it: ``flag_hash`` only, never answers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    challenge_id: ChallengeId
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    points: StrictInt = Field(ge=0)
    flag_hash: FlagHash


def to_solver_item(item: ChallengeItem) -> SolverChallengeItem:
    """Strip the answer key from a setter-side item."""
    return SolverChallengeItem(
        challenge_id=item.challenge_id,
        title=item.title,
        prompt=item.prompt,
        points=item.points,
        flag_hash=item.flag_hash,
    )


class ScoreResult(BaseModel):
    """What a scorer returns. ``0 <= points <= max_points``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    points: StrictInt = Field(ge=0)
    max_points: StrictInt = Field(ge=0)
    detail: str

    @model_validator(mode="after")
    def _points_within_max(self) -> ScoreResult:
        if self.points > self.max_points:
            raise ValueError(f"points ({self.points}) must not exceed max_points ({self.max_points})")
        return self


def clamp_score(points: int, max_points: int, detail: str = "") -> tuple[ScoreResult, bool]:
    """Clamp ``points`` into ``[0, max_points]``. Returns ``(result, was_clamped)``.

    For hosts that clamp out-of-range scorer output and log it, as the spec requires.
    """
    for name, value in (("points", points), ("max_points", max_points)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if max_points < 0:
        raise ValueError("max_points must be >= 0")
    clamped = min(max(points, 0), max_points)
    return ScoreResult(points=clamped, max_points=max_points, detail=detail), clamped != points


Cell = StrictStr | StrictInt | StrictFloat | None


class PanelRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    value: Cell


class PanelData(BaseModel):
    """What a panel returns: a title plus either ``rows`` or ``columns`` + ``table``. Data only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1)
    rows: list[PanelRow] | None = None
    columns: list[str] | None = None
    table: list[list[Cell]] | None = None

    @model_validator(mode="after")
    def _one_layout(self) -> PanelData:
        has_rows = self.rows is not None
        has_table = self.columns is not None or self.table is not None
        if has_rows == has_table:
            raise ValueError("panel must have either 'rows' or 'columns' + 'table', not both or neither")
        if has_table:
            if self.columns is None or self.table is None:
                raise ValueError("'columns' and 'table' must be given together")
            width = len(self.columns)
            for i, row in enumerate(self.table):
                if len(row) != width:
                    raise ValueError(f"table row {i} has {len(row)} cells, expected {width}")
        return self


def parse_api_version(version: str) -> tuple[int, int]:
    """``"1.0"`` -> ``(1, 0)``. Accepts ``M.m`` or ``M.m.p``. Raises ``ValueError`` otherwise."""
    m = _API_RE.fullmatch(version) if isinstance(version, str) else None
    if m is None:
        raise ValueError(f"invalid API version {version!r}: expected 'MAJOR.MINOR'")
    return int(m.group(1)), int(m.group(2))


def is_api_compatible(plugin_api: object, host_api: str = PLUGIN_API) -> bool:
    """True if ``plugin_api`` has the same major version as ``host_api`` (LR-2)."""
    try:
        return parse_api_version(plugin_api)[0] == parse_api_version(host_api)[0]  # type: ignore[arg-type]
    except ValueError:
        return False
