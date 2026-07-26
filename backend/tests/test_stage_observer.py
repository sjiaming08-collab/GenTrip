import pytest

from src.graph.state import build_initial_state
from src.runtime.stage_observer import observe_node, reset_stage_emitter, set_stage_emitter


@pytest.mark.asyncio
async def test_observed_node_emits_running_before_node_result():
    events: list[dict] = []

    async def emit(event: dict):
        events.append(event)

    async def node(_state: dict):
        assert events == [{"phase": "poi_retrieve", "status": "running", "summary": "poi_retrieve started"}]
        return {"candidate_pois": []}

    token = set_stage_emitter(emit)
    try:
        result = await observe_node("poi_retrieve", node)(build_initial_state("黄浦区吃日料"))
    finally:
        reset_stage_emitter(token)

    assert result == {"candidate_pois": []}
