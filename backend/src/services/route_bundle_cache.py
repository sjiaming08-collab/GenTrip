"""In-process RouteBundle hot cache for validated cold-path results.

The cache deliberately stores only non-user-specific route artifacts. Its
signature contains the constraints that affect feasibility so a cache hit can
skip retrieval, generation, and full evaluation while route validation still
runs for the current request.
"""

from __future__ import annotations

import json
import re
import time
from hashlib import sha256
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .cache_service import TTLCache
from .poi_query_parser import parse_retrieval_plan
from ..config import settings


@dataclass(frozen=True)
class RouteBundle:
    bundle_id: str
    signature: str
    scored_routes: list[dict[str, Any]]
    constraints: dict[str, Any]
    created_at: float
    source: str = "local_ttl"
    match_score: float = 1.0


def route_bundle_scope_eligible(state: dict[str, Any]) -> bool:
    """Only district-explicit routes may enter the district-level bundle cache."""
    constraints = state.get("constraints") or {}
    district = str(constraints.get("district") or "")
    query = str(constraints.get("raw_query") or state.get("user_query") or "")
    if not district or (district not in query and district.removesuffix("区") not in query):
        return False
    geo_scope = state.get("geo_scope") or {}
    return not geo_scope or geo_scope.get("scope_type") == "district"


class RouteBundleCache:
    def __init__(self, ttl_seconds: int | None = None) -> None:
        self.ttl_seconds = ttl_seconds or settings.route_bundle_cache_ttl_seconds
        self._cache = TTLCache(ttl_seconds=self.ttl_seconds)
        self._recent: dict[str, RouteBundle] = {}

    @staticmethod
    def _requested_categories(constraints: dict[str, Any]) -> list[str]:
        query = str(constraints.get("raw_query") or "")
        if not query:
            return []
        try:
            plan = parse_retrieval_plan({"user_query": query, "constraints": constraints})
        except (TypeError, ValueError):
            return []
        return sorted({
            f"{spec.domain.value}:{category}"
            for spec in plan.domains
            for category in spec.categories or []
        })

    @staticmethod
    def _requested_category_groups(constraints: dict[str, Any]) -> dict[str, set[str]]:
        groups: dict[str, set[str]] = {}
        for item in RouteBundleCache._requested_categories(constraints):
            domain, category = item.split(":", 1)
            groups.setdefault(domain, set()).add(category)
        return groups

    @staticmethod
    def signature(constraints: dict[str, Any]) -> str:
        payload = {
            "city": constraints.get("city"),
            "district": constraints.get("district"),
            "domains": sorted(str(item) for item in constraints.get("domains") or []),
            "cuisines": sorted(str(item) for item in constraints.get("preferred_cuisines") or []),
            "requested_categories": RouteBundleCache._requested_categories(constraints),
            "excluded": sorted(str(item) for item in constraints.get("excluded_categories") or []),
            "budget_band": int(constraints.get("budget_per_person") or 0) // 25,
            "time_band": int(constraints.get("time_budget_minutes") or 180) // 30,
            "start_at": constraints.get("start_at"),
            "return_by": constraints.get("return_by"),
            "queue_tolerance_minutes": constraints.get("queue_tolerance_minutes"),
            "poi_count": constraints.get("poi_count"),
            "anchor_count_explicit": constraints.get("anchor_count_explicit"),
            "scene_type": constraints.get("scene_type"),
            "pace": constraints.get("pace"),
            "mobility_preferences": sorted(
                str(item) for item in constraints.get("mobility_preferences") or []
            ),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _redis_key(signature: str) -> str:
        digest = sha256(signature.encode("utf-8")).hexdigest()
        return f"gentrip:route-bundle:v2:{digest}"

    @staticmethod
    def _redis_index_key() -> str:
        return "gentrip:route-bundle:v2:index"

    @staticmethod
    def _has_required_route_shape(bundle: RouteBundle, constraints: dict[str, Any]) -> bool:
        query = str(constraints.get("raw_query") or "")
        explicit_count = bool(re.search(
            r"(?:\d{1,2}|[一二两三四五六七八九十]+)\s*个?\s*(?:活动|地点|景点|去处|项目|站)",
            query,
        ))
        required_stops = max(1, int(constraints.get("poi_count") or 1)) if explicit_count or not query else 1
        preferred = [str(item) for item in constraints.get("preferred_cuisines") or []]
        requested_groups = RouteBundleCache._requested_category_groups(constraints)
        for item in bundle.scored_routes:
            stops = ((item.get("route") or {}).get("stops") or [])
            if len(stops) < required_stops:
                continue
            if preferred and not any(
                any(term in str(stop.get("category") or "") or term in str(stop.get("poi_name") or "") for term in preferred)
                for stop in stops
            ):
                continue
            actual_categories = {str(stop.get("category") or "") for stop in stops}
            if any(
                not actual_categories.intersection(categories)
                for categories in requested_groups.values()
            ):
                continue
            return True
        return False

    @staticmethod
    def _normalized(constraints: dict[str, Any]) -> dict[str, Any]:
        return {
            "city": constraints.get("city"),
            "district": constraints.get("district"),
            "domains": sorted(str(item) for item in constraints.get("domains") or []),
            "cuisines": sorted(str(item) for item in constraints.get("preferred_cuisines") or []),
            "requested_categories": RouteBundleCache._requested_categories(constraints),
            "excluded": sorted(str(item) for item in constraints.get("excluded_categories") or []),
            "budget": int(constraints.get("budget_per_person") or 0),
            "time": int(constraints.get("time_budget_minutes") or 180),
            "start": constraints.get("start_at") or "",
            "return": constraints.get("return_by") or "",
            "queue": constraints.get("queue_tolerance_minutes"),
            "poi_count": int(constraints.get("poi_count") or 3),
        }

    @staticmethod
    def _clock_minutes(value: object) -> int:
        if not isinstance(value, str) or ":" not in value:
            return 0
        hour, minute = value.split(":", 1)
        return int(hour) * 60 + int(minute) if hour.isdigit() and minute.isdigit() else 0

    @classmethod
    def similarity(cls, query: dict[str, Any], candidate: dict[str, Any]) -> float:
        """Structured feature-vector similarity with hard feasibility guards."""
        left = cls._normalized(query)
        right = cls._normalized(candidate)
        if (
            left["city"] != right["city"]
            or left["district"] != right["district"]
            or left["domains"] != right["domains"]
            or left["cuisines"] != right["cuisines"]
            or left["requested_categories"] != right["requested_categories"]
            or left["excluded"] != right["excluded"]
            or left["poi_count"] != right["poi_count"]
        ):
            return 0.0

        def ratio(a: int, b: int) -> float:
            return max(0.0, 1.0 - abs(a - b) / max(a, b, 1))

        start_score = ratio(cls._clock_minutes(left["start"]), cls._clock_minutes(right["start"])) if left["start"] and right["start"] else float(left["start"] == right["start"])
        return_score = ratio(cls._clock_minutes(left["return"]), cls._clock_minutes(right["return"])) if left["return"] and right["return"] else float(left["return"] == right["return"])
        queue_score = ratio(int(left["queue"] or 0), int(right["queue"] or 0)) if left["queue"] is not None and right["queue"] is not None else float(left["queue"] == right["queue"])
        score = (
            0.30 * ratio(left["budget"], right["budget"])
            + 0.30 * ratio(left["time"], right["time"])
            + 0.15 * start_score
            + 0.15 * return_score
            + 0.05 * queue_score
            + 0.05 * ratio(left["poi_count"], right["poi_count"])
        )
        return round(score, 3)

    def _similar_local(self, constraints: dict[str, Any]) -> RouteBundle | None:
        now = time.time()
        best: RouteBundle | None = None
        for signature, bundle in list(self._recent.items()):
            if now - bundle.created_at >= self.ttl_seconds:
                self._recent.pop(signature, None)
                continue
            score = self.similarity(constraints, bundle.constraints)
            if (
                score >= settings.route_bundle_min_match_score
                and self._has_required_route_shape(bundle, constraints)
                and (best is None or score > best.match_score)
            ):
                best = RouteBundle(
                    bundle_id=bundle.bundle_id,
                    signature=bundle.signature,
                    scored_routes=bundle.scored_routes,
                    constraints=bundle.constraints,
                    created_at=bundle.created_at,
                    source="local_similarity",
                    match_score=score,
                )
        return best

    async def get(self, constraints: dict[str, Any]) -> RouteBundle | None:
        signature = self.signature(constraints)
        local = self._cache.get(signature)
        if local is not None and self._has_required_route_shape(local, constraints):
            return local
        local_similar = self._similar_local(constraints)
        if local_similar is not None:
            return local_similar
        if not settings.redis_url:
            return None
        try:
            import redis.asyncio as redis

            client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                protocol=2,
                socket_connect_timeout=0.2,
                socket_timeout=0.5,
            )
            try:
                raw = await client.get(self._redis_key(signature))
            finally:
                await client.aclose()
            if raw:
                payload = json.loads(raw)
                bundle = RouteBundle(
                    bundle_id=str(payload["bundle_id"]),
                    signature=signature,
                    scored_routes=list(payload.get("scored_routes") or []),
                    constraints=dict(payload.get("constraints") or constraints),
                    created_at=float(payload.get("created_at") or time.time()),
                    source="redis",
                )
                if self._has_required_route_shape(bundle, constraints):
                    self._cache.set(signature, bundle)
                    self._recent[signature] = bundle
                    return bundle

            client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                protocol=2,
                socket_connect_timeout=0.2,
                socket_timeout=0.5,
            )
            try:
                now = time.time()
                await client.zremrangebyscore(self._redis_index_key(), "-inf", now)
                keys = await client.zrangebyscore(self._redis_index_key(), now, "+inf", start=0, num=50)
                payloads = await client.mget(keys) if keys else []
            finally:
                await client.aclose()
            best: RouteBundle | None = None
            for key, raw_payload in zip(keys, payloads):
                if not raw_payload:
                    continue
                payload = json.loads(raw_payload)
                score = self.similarity(constraints, dict(payload.get("constraints") or {}))
                if score < settings.route_bundle_min_match_score or (best is not None and score <= best.match_score):
                    continue
                bundle = RouteBundle(
                    bundle_id=str(payload["bundle_id"]),
                    signature=str(key),
                    scored_routes=list(payload.get("scored_routes") or []),
                    constraints=dict(payload.get("constraints") or {}),
                    created_at=float(payload.get("created_at") or now),
                    source="redis_similarity",
                    match_score=score,
                )
                if not self._has_required_route_shape(bundle, constraints):
                    continue
                best = bundle
            if best is not None:
                self._recent[best.signature] = best
            return best
        except Exception:
            return None

    async def put(self, constraints: dict[str, Any], scored_routes: list[dict[str, Any]]) -> RouteBundle | None:
        if not scored_routes:
            return None
        signature = self.signature(constraints)
        bundle = RouteBundle(
            bundle_id=f"local-{uuid4()}",
            signature=signature,
            scored_routes=[dict(item) for item in scored_routes[:3]],
            constraints=dict(constraints),
            created_at=time.time(),
        )
        self._cache.set(signature, bundle)
        self._recent[signature] = bundle
        if settings.redis_url:
            try:
                import redis.asyncio as redis

                client = redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    protocol=2,
                    socket_connect_timeout=0.2,
                    socket_timeout=0.5,
                )
                try:
                    key = self._redis_key(signature)
                    expires_at = time.time() + self.ttl_seconds
                    await client.set(
                        key,
                        json.dumps({"bundle_id": bundle.bundle_id, "scored_routes": bundle.scored_routes, "constraints": bundle.constraints, "created_at": bundle.created_at}, ensure_ascii=False),
                        ex=self.ttl_seconds,
                    )
                    await client.zadd(self._redis_index_key(), {key: expires_at})
                    await client.zremrangebyscore(self._redis_index_key(), "-inf", time.time())
                    await client.expire(self._redis_index_key(), self.ttl_seconds * 2)
                finally:
                    await client.aclose()
            except Exception:
                pass
        return bundle

    def clear(self) -> None:
        self._cache.clear()
        self._recent.clear()


route_bundle_cache = RouteBundleCache()
