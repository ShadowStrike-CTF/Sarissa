"""Difficulty rubric: four factors (0-3) -> score 0-12 -> tier D1-D5 -> 100-500 points.

    score  0-2  -> D1 -> 100
    score  3-5  -> D2 -> 200
    score  6-8  -> D3 -> 300
    score  9-10 -> D4 -> 400
    score 11-12 -> D5 -> 500
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from .poe import DifficultyFactors

MIN_SCORE = 0
MAX_SCORE = 12


class Tier(StrEnum):
    D1 = "D1"
    D2 = "D2"
    D3 = "D3"
    D4 = "D4"
    D5 = "D5"


# (inclusive upper bound of score, tier)
_TIER_BOUNDS: tuple[tuple[int, Tier], ...] = (
    (2, Tier.D1),
    (5, Tier.D2),
    (8, Tier.D3),
    (10, Tier.D4),
    (12, Tier.D5),
)

TIER_POINTS: dict[Tier, int] = {
    Tier.D1: 100,
    Tier.D2: 200,
    Tier.D3: 300,
    Tier.D4: 400,
    Tier.D5: 500,
}


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    score: StrictInt = Field(ge=MIN_SCORE, le=MAX_SCORE)
    tier: Tier
    points: StrictInt = Field(ge=0)


class PointsOverride(BaseModel):
    """A manual points value that replaces the rubric result. Must say why."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    points: StrictInt = Field(ge=0)
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("override reason must not be blank")
        return value


def score_factors(factors: DifficultyFactors) -> int:
    """Sum of the four factors (0-12)."""
    return factors.tool_coverage + factors.hops + factors.obscurity + factors.traps


def tier_for_score(score: int) -> Tier:
    if isinstance(score, bool) or not isinstance(score, int):
        raise TypeError(f"score must be an int, got {type(score).__name__}")
    if not MIN_SCORE <= score <= MAX_SCORE:
        raise ValueError(f"score must be {MIN_SCORE}-{MAX_SCORE}, got {score}")
    for upper, tier in _TIER_BOUNDS[:-1]:
        if score <= upper:
            return tier
    return _TIER_BOUNDS[-1][1]


def points_for_tier(tier: Tier | str) -> int:
    return TIER_POINTS[Tier(tier)]


def assess(factors: DifficultyFactors) -> Assessment:
    """Score, tier and points for a set of factors."""
    s = score_factors(factors)
    t = tier_for_score(s)
    return Assessment(score=s, tier=t, points=TIER_POINTS[t])


def override(points: int, reason: str) -> PointsOverride:
    """Replace the rubric points. ``reason`` must be non-blank; raises ``ValueError`` otherwise."""
    return PointsOverride(points=points, reason=reason)
