"""Point-of-entry (PoE) record: one findable thing in an extraction."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints

from .hashing import HashString
from .ids import PoeId

PARSER_PATTERN = r"^[^\s:@]+:[^\s:@]+@[^\s:@]+$"
Parser = Annotated[str, StringConstraints(pattern=PARSER_PATTERN)]
"""``"{tool}:{module}@{version}"``."""

Factor = Annotated[StrictInt, Field(ge=0, le=3)]


class RecordState(StrEnum):
    LIVE = "live"
    DELETED = "deleted"
    WAL_UNCHECKPOINTED = "wal_uncheckpointed"
    FREELIST = "freelist"
    CARVED = "carved"


class ToolCoverage(StrEnum):
    AUTO_COMMERCIAL = "auto_commercial"
    AUTO_OPEN = "auto_open"
    MANUAL_QUERY = "manual_query"
    CUSTOM_SCRIPT = "custom_script"


class DifficultyFactors(BaseModel):
    """Four rubric factors, each 0-3. See :mod:`megdan_schema.rubric`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_coverage: Factor
    hops: Factor
    obscurity: Factor
    traps: Factor


class PoERecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    poe_id: PoeId
    source_image_hash: HashString
    artefact_path: str = Field(min_length=1)
    artefact_file_hash: HashString
    locator: dict[str, Any]
    record_state: RecordState
    raw_value: str
    normalised_value: str
    normalisation_rule: str = Field(min_length=1)
    parser: Parser
    how_to_find: str = Field(min_length=1)
    tool_coverage: ToolCoverage
    difficulty_factors: DifficultyFactors
    points: Annotated[StrictInt, Field(ge=0)]
    trap_tags: list[str] = Field(default_factory=list)
    related_poe: list[PoeId] = Field(default_factory=list)
