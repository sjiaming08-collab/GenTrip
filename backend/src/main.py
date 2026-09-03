"""FastAPI 入口。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.container import plan_service
from .api.routes import router
from .api.sse import router as sse_router
from .config import settings
from .llm.client import close_llm_client
from .observability.tracing import instrument_fastapi
from .services.amap_poi_provider import close_amap_poi_provider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("gentrip.graph").setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await plan_service.initialize()
    try:
        yield
    finally:
        await close_amap_poi_provider()
        await close_llm_client()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="GenTrip local Beta planning runtime",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix=settings.api_prefix)
    app.include_router(sse_router, prefix=settings.api_prefix)
    instrument_fastapi(app)
    return app


app = create_app()
