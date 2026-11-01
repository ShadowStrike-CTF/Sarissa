"""Set manifest: what a challenge set was built from, and with which tool versions."""

from __future__ import annotations

from datetime import timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, field_validator

from .hashing import HashString
from .ids import SetId


class SetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    set_id: SetId
    seed: StrictInt
    source_image_hash: HashString
    poligon_version: str = Field(min_length=1)
    treska_version: str = Field(min_length=1)
    created_utc: AwareDatetime

    @field_validator("created_utc")
    @classmethod
    def _must_be_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("created_utc must be in UTC (offset +00:00)")
        return value
