"""Per-run node lifecycle events without serializing callbacks into GraphState."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Awaitable, Callable

from ..graph.state import GraphState

StageEmitter = Callable[[dict[str, Any]], Awaitable[Any]]
_stage_emitter: ContextVar[StageEmitter | None] = ContextVar("gentrip_stage_emitter", default=None)


def set_stage_emitter(emitter: StageEmitter) -> Token[StageEmitter | None]:
    return _stage_emitter.set(emitter)


def reset_stage_emitter(token: Token[StageEmitter | None]) -> None:
    _stage_emitter.reset(token)


def observe_node(phase: str, node: Callable[[GraphState], Awaitable[dict]]) -> Callable[[GraphState], Awaitable[dict]]:
    async def wrapped(state: GraphState) -> dict:
        emitter = _stage_emitter.get()
        if emitter is not None:
            await emitter({"phase": phase, "status": "running", "summary": f"{phase} started"})
        return await node(state)

    wrapped.__name__ = f"observed_{phase}"
    return wrapped
