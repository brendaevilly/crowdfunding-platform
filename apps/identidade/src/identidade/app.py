"""Aplicação FastAPI do microsserviço Identidade."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from identidade.config import broker_url_padrao, identidade_url_padrao
from identidade.contas.rotas import criar_contas_router
from shared.db import migrate
from shared.http.app import create_app
from shared.messaging import configure_messaging
from shared.messaging_schema import install_messaging_schema

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def criar_identidade_app(data_dir: str | Path = "data") -> FastAPI:
    """Fábrica do aplicativo FastAPI da Identidade."""
    app = create_app("identidade", version="0.1.0")

    contas_router = criar_contas_router(data_dir)
    app.include_router(contas_router)
    app.include_router(contas_router, prefix="/identidade")

    @asynccontextmanager
    async def identidade_lifespan(application: FastAPI) -> AsyncIterator[None]:
        migrate("identidade", MIGRATIONS_DIR, data_dir)
        install_messaging_schema("identidade", data_dir)
        logger.info("Migrations da Identidade aplicadas com sucesso")
        yield

    app.router.lifespan_context = identidade_lifespan

    habilitar_messaging = os.getenv("IDENTIDADE_MESSAGING_ENABLED", "true").lower() in (
        "true",
        "1",
        "yes",
    )

    if habilitar_messaging:
        configure_messaging(
            app,
            service="identidade",
            service_url=identidade_url_padrao(),
            broker_url=broker_url_padrao(),
            handlers={},
            data_dir=data_dir,
        )

    return app


app = criar_identidade_app()
