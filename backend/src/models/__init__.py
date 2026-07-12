"""领域模型 — Constraints / Route / Assumption 等。"""

from .constraints import Assumption, Constraints, IntentDomain
from .diff import DiffEntry, RoutePlanDiff
from .memory import MemoryContext
from .profile import UserProfile
from .reply import AgentReply, AgentReplyMeta, ReplyType
from .route import (
    RoutePlan,
    RoutePlanResult,
    RouteSource,
    RouteStop,
    ScoredPoi,
    ScoredRoute,
    ValidationReport,
)
from .session import RouteIntent, SessionState, Turn

__all__ = [
    "AgentReply",
    "AgentReplyMeta",
    "Assumption",
    "Constraints",
    "DiffEntry",
    "IntentDomain",
    "MemoryContext",
    "ReplyType",
    "RouteIntent",
    "RoutePlan",
    "RoutePlanDiff",
    "RoutePlanResult",
    "RouteSource",
    "RouteStop",
    "ScoredPoi",
    "ScoredRoute",
    "SessionState",
    "Turn",
    "UserProfile",
    "ValidationReport",
]
