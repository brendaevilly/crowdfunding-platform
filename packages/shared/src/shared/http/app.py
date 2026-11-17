"""Fábrica comum de servidor: create_app(name)."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel
from starlette.types import Lifespan

from shared.config import Settings
from shared.http.errors import ErrorResponse, register_error_handlers
from shared.http.middleware import CorrelationIdMiddleware
from shared.logging import configure_logging


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


def create_app(
    name: str,
    *,
    version: str = "0.0.0",
    configure_logs: bool = True,
    include_health: bool = True,
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    """FastAPI do serviço: logging JSON, correlation-id, /health e erros padronizados.

    `include_health=False` deixa o serviço definir o próprio /health (ex.: o gateway agrega).
    """
    if configure_logs:
        configure_logging(name, Settings.from_env().log_level)

    app = FastAPI(
        title=name,
        version=version,
        lifespan=lifespan,
        responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    app.add_middleware(CorrelationIdMiddleware)
    register_error_handlers(app)

    if include_health:

        @app.get("/health", response_model=HealthResponse, tags=["infra"])
        async def health() -> HealthResponse:
            return HealthResponse(status="ok", service=name, version=version)

    return app
