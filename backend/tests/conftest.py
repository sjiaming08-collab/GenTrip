import pytest
from httpx import ASGITransport, AsyncClient

from src.api.container import plan_service as app_plan_service
from src.config import settings
from src.main import app
from src.observability.metrics import runtime_metrics
from src.runtime.events import RuntimeEventBus
from src.runtime.store import MemoryRuntimeStore
from src.services.plan_service import PlanService
from src.services.route_bundle_cache import route_bundle_cache


@pytest.fixture(autouse=True)
def disable_live_llm(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", False)
    monkeypatch.setattr(settings, "llm_api_key", "")


@pytest.fixture(autouse=True)
def isolate_runtime_dependencies(monkeypatch, request):
    """Keep unit tests deterministic while opt-in integration tests use local services."""
    if request.node.get_closest_marker("runtime_integration"):
        return
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "redis_url", "")
    app_plan_service._store = MemoryRuntimeStore()
    app_plan_service._event_bus = RuntimeEventBus()
    app_plan_service._initialized = False
    app_plan_service._tasks.clear()
    route_bundle_cache.clear()
    runtime_metrics.reset()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def plan_service():
    return PlanService()
