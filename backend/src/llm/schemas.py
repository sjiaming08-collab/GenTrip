"""LLM 结构化输出 schema。

约束模型只描述当前 query 中的显式语义。会话记忆、默认值和派生值由
``constraint_service`` 统一处理，避免模型与规则层同时拥有同一字段。
"""

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from ..models.constraints import IntentDomain


class GeoMention(BaseModel):
    text: str
    relation: Literal["exact", "nearby", "within_area"] = "exact"
    evidence: str


class TimeExpression(BaseModel):
    kind: Literal["exact_duration", "clock_window", "daypart", "full_day", "none"] = "none"
    start_at: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    return_by: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    duration_minutes: int | None = Field(default=None, gt=0)
    qualifier: Literal["exact", "around", "maximum", "minimum"] | None = None
    evidence: str | None = None


class ActivityExpression(BaseModel):
    text: str
    domain_hint: IntentDomain | None = None
    categories: list[str] = Field(default_factory=list)
    modality: Literal["required", "preferred", "prohibited"] = "required"
    evidence: str


class LlmAssumption(BaseModel):
    """旧版返回兼容结构；新契约不再要求 LLM 生成 assumptions。"""

    slot: str
    assumed_value: str
    message: str
    source: str = "llm_inferred"


class ConstraintExtractResult(BaseModel):
    """当前轮显式约束，兼容接收旧字段名。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    contract_version: Literal[1, 2, 3] = 1
    turn_mode: Literal["plan", "reject"] = "plan"
    primary_intent: str = ""
    query_understanding: str = ""
    domains_explicit: list[IntentDomain] = Field(
        default_factory=list,
        validation_alias=AliasChoices("domains_explicit", "domains"),
    )
    city_explicit: str | None = Field(
        default=None,
        validation_alias=AliasChoices("city_explicit", "city"),
    )
    district_explicit: str | None = Field(
        default=None,
        validation_alias=AliasChoices("district_explicit", "district"),
    )
    time_budget_minutes_explicit: int | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices(
            "time_budget_minutes_explicit", "time_budget_minutes"
        ),
    )
    start_at_explicit: str | None = Field(
        default=None,
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$",
        validation_alias=AliasChoices("start_at_explicit", "start_at"),
    )
    return_by_explicit: str | None = Field(
        default=None,
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$",
        validation_alias=AliasChoices("return_by_explicit", "return_by"),
    )
    queue_tolerance_minutes_explicit: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices(
            "queue_tolerance_minutes_explicit", "queue_tolerance_minutes"
        ),
    )
    budget_per_person_explicit: int | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices(
            "budget_per_person_explicit", "budget_per_person"
        ),
    )
    anchor_count_explicit: int | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices(
            "anchor_count_explicit", "poi_count_explicit", "poi_count"
        ),
    )
    preferred_cuisines_explicit: list[str] | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "preferred_cuisines_explicit", "preferred_cuisines"
        ),
    )
    activity_tags_explicit: list[str] | None = Field(
        default=None,
        validation_alias=AliasChoices("activity_tags_explicit", "activity_tags"),
    )
    location_mentions_explicit: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "location_mentions_explicit", "location_mentions"
        ),
    )
    excluded_categories_explicit: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "excluded_categories_explicit", "excluded_categories"
        ),
    )
    sequence_preferences_explicit: list[str] = Field(default_factory=list)
    scene_type_explicit: Literal["solo", "couple", "friends", "family"] | None = None
    pace_explicit: Literal["relaxed", "balanced", "packed"] | None = None
    mobility_preferences_explicit: list[str] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)
    geo_mentions: list[GeoMention] = Field(default_factory=list)
    time_expression: TimeExpression | None = None
    activities: list[ActivityExpression] = Field(default_factory=list)

    # Transition-only: ignored by the deterministic constraint resolver.
    assumptions: list[LlmAssumption] = Field(default_factory=list, exclude=True)

    @property
    def domains(self) -> list[IntentDomain]:
        return self.domains_explicit

    @property
    def city(self) -> str | None:
        return self.city_explicit

    @property
    def district(self) -> str | None:
        return self.district_explicit

    @property
    def time_budget_minutes(self) -> int | None:
        return self.time_budget_minutes_explicit

    @property
    def start_at(self) -> str | None:
        return self.start_at_explicit

    @property
    def return_by(self) -> str | None:
        return self.return_by_explicit

    @property
    def queue_tolerance_minutes(self) -> int | None:
        return self.queue_tolerance_minutes_explicit

    @property
    def budget_per_person(self) -> int | None:
        return self.budget_per_person_explicit

    @property
    def poi_count(self) -> int | None:
        return self.anchor_count_explicit

    @property
    def preferred_cuisines(self) -> list[str] | None:
        return self.preferred_cuisines_explicit

    @property
    def activity_tags(self) -> list[str] | None:
        return self.activity_tags_explicit

    @property
    def location_mentions(self) -> list[str]:
        return self.location_mentions_explicit

    @property
    def excluded_categories(self) -> list[str]:
        return self.excluded_categories_explicit
