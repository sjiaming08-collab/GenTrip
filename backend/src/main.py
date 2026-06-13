"""FastAPI 入口。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="GenTrip API — Step A cold path",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
