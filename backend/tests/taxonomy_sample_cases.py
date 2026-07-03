"""taxonomy 映射验收用例 — 供 pytest 与 verify_taxonomy_samples.py 共用。"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.models.constraints import TripPurpose

CHINESE_LEAVES = frozenset({"本帮菜", "火锅", "小吃快餐", "川菜", "粤菜", "烧烤"})
DINING_LEAVES = CHINESE_LEAVES | frozenset({"西餐", "日料", "咖啡", "甜品", "酒吧"})
SIGHTSEEING_LEAVES = frozenset({"观光", "博物馆", "文化", "公园"})


@dataclass(frozen=True)
class TaxonomySampleCase:
    """单条 POI 召回映射验收用例。"""

    id: str
    description: str
    district: str | None
    purpose: str | None
    preferred_cuisines: list[str] | None = None
    activity_tags: list[str] | None = None
    budget_per_person: int | None = None
    allowed_categories: frozenset[str] | None = None
    forbidden_categories: frozenset[str] = field(default_factory=frozenset)
    min_pois: int = 1
    allowed_relax_steps: frozenset[str] | None = None
    require_assumption_slot: str | None = None
    require_assumption_message_contains: str | None = None
    require_any_category_in: frozenset[str] | None = None


TAXONOMY_SAMPLE_CASES: tuple[TaxonomySampleCase, ...] = (
    TaxonomySampleCase(
        id="chinese_group",
        description="group 中餐 → 中餐叶子，排除外国餐/轻食/观光",
        district="徐汇区",
        purpose=TripPurpose.DINING.value,
        preferred_cuisines=["中餐"],
        allowed_categories=CHINESE_LEAVES,
        forbidden_categories=frozenset({"西餐", "日料", "咖啡", "博物馆", "购物"}),
        allowed_relax_steps=frozenset({"R0"}),
    ),
    TaxonomySampleCase(
        id="benbang_leaf",
        description="leaf 本帮 → 仅本帮菜",
        district="徐汇区",
        purpose=TripPurpose.DINING.value,
        preferred_cuisines=["本帮"],
        allowed_categories=frozenset({"本帮菜"}),
        forbidden_categories=frozenset({"小吃快餐", "咖啡", "西餐", "博物馆"}),
        allowed_relax_steps=frozenset({"R0"}),
    ),
    TaxonomySampleCase(
        id="alias_chinese_food",
        description="alias 中国菜 → 同中餐 group 展开",
        district="静安区",
        purpose=TripPurpose.DINING.value,
        preferred_cuisines=["中国菜"],
        allowed_categories=CHINESE_LEAVES,
        forbidden_categories=frozenset({"西餐", "日料", "咖啡"}),
    ),
    TaxonomySampleCase(
        id="japanese_leaf",
        description="leaf 日料 → 仅日料",
        district="静安区",
        purpose=TripPurpose.DINING.value,
        preferred_cuisines=["日料"],
        allowed_categories=frozenset({"日料"}),
        forbidden_categories=frozenset({"本帮菜", "西餐", "博物馆"}),
    ),
    TaxonomySampleCase(
        id="coffee_leaf",
        description="leaf 咖啡 → 仅咖啡",
        district="徐汇区",
        purpose=TripPurpose.DINING.value,
        preferred_cuisines=["咖啡"],
        allowed_categories=frozenset({"咖啡"}),
        forbidden_categories=frozenset({"本帮菜", "酒吧", "博物馆"}),
    ),
    TaxonomySampleCase(
        id="sightseeing_museum",
        description="purpose SIGHTSEEING → 仅观光类叶子",
        district="徐汇区",
        purpose=TripPurpose.SIGHTSEEING.value,
        allowed_categories=SIGHTSEEING_LEAVES,
        forbidden_categories=frozenset({"本帮菜", "咖啡", "西餐", "小吃快餐"}),
        allowed_relax_steps=frozenset({"R0"}),
    ),
    TaxonomySampleCase(
        id="sichuan_widen",
        description="leaf 川菜无 POI → R2 扩到中餐 + assumption",
        district="徐汇区",
        purpose=TripPurpose.DINING.value,
        preferred_cuisines=["川菜"],
        allowed_categories=CHINESE_LEAVES,
        forbidden_categories=frozenset({"西餐", "日料", "咖啡"}),
        allowed_relax_steps=frozenset({"R2", "R3", "R4", "R5"}),
        require_assumption_slot="preferred_cuisines",
        require_assumption_message_contains="扩展",
    ),
    TaxonomySampleCase(
        id="dining_no_preferred",
        description="DINING 无 preferred → 全餐饮叶子，可比中餐更宽",
        district="徐汇区",
        purpose=TripPurpose.DINING.value,
        allowed_categories=DINING_LEAVES,
        require_any_category_in=frozenset({"咖啡", "本帮菜"}),
    ),
    TaxonomySampleCase(
        id="mixed_guangchi",
        description="MIXED + 逛吃 → 餐饮与观光并集",
        district="徐汇区",
        purpose=TripPurpose.MIXED.value,
        activity_tags=["逛吃"],
        require_any_category_in=frozenset({"本帮菜", "咖啡", "小吃快餐"}),
        forbidden_categories=frozenset(),
    ),
    TaxonomySampleCase(
        id="western_leaf",
        description="leaf 西餐 → 仅西餐（与中餐互斥对照）",
        district="徐汇区",
        purpose=TripPurpose.DINING.value,
        preferred_cuisines=["西餐"],
        allowed_categories=frozenset({"西餐"}),
        forbidden_categories=frozenset({"本帮菜", "小吃快餐", "日料"}),
    ),
)


@dataclass
class CaseResult:
    case: TaxonomySampleCase
    passed: bool
    errors: list[str]
    relax_step: str
    categories: list[str]
    final_leaves: list[str]
    assumptions: list[str]


def run_sample_case(case: TaxonomySampleCase, *, limit: int = 10) -> CaseResult:
    from src.mocks.poi_store import retrieve_pois_with_meta

    result = retrieve_pois_with_meta(
        district=case.district,
        limit=limit,
        purpose=case.purpose,
        preferred_cuisines=case.preferred_cuisines,
        activity_tags=case.activity_tags,
        budget_per_person=case.budget_per_person,
    )

    categories = [p.category for p in result.pois]
    assumption_messages = [a.message for a in result.assumptions]
    errors: list[str] = []

    if len(result.pois) < case.min_pois:
        errors.append(f"POI 数量不足: {len(result.pois)} < {case.min_pois}")

    if case.allowed_relax_steps is not None and result.relax_step not in case.allowed_relax_steps:
        errors.append(
            f"relax_step={result.relax_step}, 期望 ∈ {sorted(case.allowed_relax_steps)}"
        )

    if case.allowed_categories is not None:
        bad = {c for c in categories if c not in case.allowed_categories}
        if bad:
            errors.append(f"出现不允许的类目: {sorted(bad)}")

    forbidden_hit = {c for c in categories if c in case.forbidden_categories}
    if forbidden_hit:
        errors.append(f"出现禁止类目: {sorted(forbidden_hit)}")

    if case.require_any_category_in is not None:
        if not ({c for c in categories} & case.require_any_category_in):
            errors.append(
                f"未命中期望类目之一: {sorted(case.require_any_category_in)}"
            )

    if case.require_assumption_slot is not None:
        slots = [a.slot for a in result.assumptions]
        if case.require_assumption_slot not in slots:
            errors.append(f"缺少 assumption slot: {case.require_assumption_slot}")

    if case.require_assumption_message_contains is not None:
        if not any(
            case.require_assumption_message_contains in msg for msg in assumption_messages
        ):
            errors.append(
                "assumption 消息未包含: "
                f"{case.require_assumption_message_contains!r}"
            )

    if case.id == "mixed_guangchi":
        cats = set(categories)
        if not (cats & {"本帮菜", "咖啡", "小吃快餐", "西餐", "日料", "甜品", "酒吧"}):
            errors.append("逛吃场景未召回任何餐饮类目")
        if not (cats & SIGHTSEEING_LEAVES):
            errors.append("逛吃场景未召回任何观光类目")

    return CaseResult(
        case=case,
        passed=not errors,
        errors=errors,
        relax_step=result.relax_step,
        categories=categories,
        final_leaves=result.final_leaves,
        assumptions=assumption_messages,
    )


def run_all_sample_cases(*, limit: int = 10) -> list[CaseResult]:
    return [run_sample_case(case, limit=limit) for case in TAXONOMY_SAMPLE_CASES]
