from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.requests import Request

from core.config import AppConfig
from core.exceptions import AppError
from core.logging import configure_logging

from apps.api.dependencies import build_context
from apps.api.routers import (
    health, notebooks, sources, chat, models as models_router,
    settings as settings_router, events,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    config = AppConfig()
    app.state.ctx = build_context(config)
    yield


def create_app(config: AppConfig | None = None) -> FastAPI:
    app = FastAPI(title="Notebook Ollama", lifespan=lifespan)

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        status_map = {
            "input.invalid": 400,
            "ingestion.unsupported_kind": 400,
            "ingestion.duplicate": 409,
            "storage.not_found": 404,
            "storage.conflict": 409,
            "ollama.unreachable": 503,
            "ollama.model_not_found": 404,
            "mcp.unauthorized": 401,
        }
        return JSONResponse(
            status_code=status_map.get(exc.code.value, 500),
            content=exc.to_dict(),
        )

    app.include_router(health.router)
    app.include_router(notebooks.router)
    app.include_router(sources.router)
    app.include_router(chat.router)
    app.include_router(models_router.router)
    app.include_router(settings_router.router)
    app.include_router(events.router)
    return app


app = create_app()
