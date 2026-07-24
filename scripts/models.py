"""
Shared models for the GitHub-only pipeline. Kept intentionally lean --
Pydantic here is doing validation and camelCase serialization, not ORM work
(there's no DB in this build).

model_dump(by_alias=True) on an Opportunity produces exactly the JSON shape
your existing index.html dashboard already reads (externalKey aside, which
is new and dashboard-safe to ignore) -- so the dashboard didn't need to
change for this rebuild.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


class FitLevel(str, Enum):
    HIGH = "High"
    ADJACENT = "Adjacent"
    REVIEW = "Review"
    REVIEW_BROAD = "Review (broad match)"


class Opportunity(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)

    external_key: str
    raw_document_path: Optional[str] = None
    source: str
    name: str
    objective: Optional[str] = None
    open_date: Optional[date] = None
    close_date: Optional[date] = None
    cmmc_requirement: Optional[str] = None
    funding_amount: Optional[str] = None
    application_url: Optional[str] = None
    notes: Optional[str] = None
    products: list[str] = Field(default_factory=list)
    fit_level: FitLevel = FitLevel.REVIEW
    match_source: str = "keyword"
    first_seen: date = Field(default_factory=date.today)
    archived: bool = False

    @field_validator("products")
    @classmethod
    def valid_products(cls, v: list[str]) -> list[str]:
        allowed = {"HAVEN", "Argus", "Hydra", "GoLynk"}
        bad = [p for p in v if p not in allowed]
        if bad:
            raise ValueError(f"Unknown product(s) {bad} -- must be a subset of {sorted(allowed)}")
        return v

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name must not be empty")
        return v.strip()

    def to_dashboard_dict(self) -> dict:
        """Serialize to the exact camelCase JSON shape index.html expects."""
        return self.model_dump(by_alias=True, mode="json")
