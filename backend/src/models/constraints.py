"""约束与假设模型。"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TripPurpose(str, Enum):
    DINING = "DINING"
    SIGHTSEEING = "SIGHTSEEING"
    SHOPPING = "SHOPPING"
    MIXED = "MIXED"


class Assumption(BaseModel):
    slot: str
    assumed_value: str
    source: str
    message: str
    overridable: bool = True


class Constraints(BaseModel):
    raw_query: str
    purpose: TripPurpose = TripPurpose.MIXED
    district: str
    time_budget_minutes: Optional[int] = None
    return_by: Optional[str] = None
    budget_per_person: int
    poi_count: int = 3
    preferred_cuisines: Optional[list[str]] = None
    activity_tags: Optional[list[str]] = None
