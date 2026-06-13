import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.services.plan_service import PlanService


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def plan_service():
    return PlanService()
