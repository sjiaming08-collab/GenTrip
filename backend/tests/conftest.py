import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.main import app
from src.services.plan_service import PlanService


@pytest.fixture(autouse=True)
def disable_live_llm(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", False)
    monkeypatch.setattr(settings, "llm_api_key", "")


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def plan_service():
    return PlanService()
