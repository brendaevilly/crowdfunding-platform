"""Aplicação FastAPI do microsserviço Custódia e Retornos."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from contracts.topicos import APORTE_CONFIRMADO, CAMPANHA_PUBLICADA
from custodia_retornos.config import broker_url_padrao, custodia_url_padrao
from custodia_retornos.custodia.consumidores import (
    consumir_aporte_confirmado,
    consumir_campanha_publicada,
)
from shared.consumer import EventHandler
from shared.db import migrate
from shared.http.app import create_app
from shared.messaging import configure_messaging
from shared.messaging_schema import install_messaging_schema

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

HANDLERS: dict[str, EventHandler] = {
    CAMPANHA_PUBLICADA: consumir_campanha_publicada,
    APORTE_CONFIRMADO: consumir_aporte_confirmado,
}


def criar_custodia_app(data_dir: str | Path = "data") -> FastAPI:
    """Cria a aplicação FastAPI de Custódia e Retornos."""

    app = create_app("custodia_retornos", version="0.1.0")

    @asynccontextmanager
    async def custodia_lifespan(application: FastAPI) -> AsyncIterator[None]:
        migrate("custodia_retornos", MIGRATIONS_DIR, data_dir)
        install_messaging_schema("custodia_retornos", data_dir)
        logger.info("Migrations da Custódia aplicadas com sucesso.")
        yield

    app.router.lifespan_context = custodia_lifespan

    habilitar_messaging = os.getenv(
        "CUSTODIA_RETORNOS_MESSAGING_ENABLED",
        "true",
    ).lower() in ("true", "1", "yes")

    if habilitar_messaging:
        configure_messaging(
            app,
            service="custodia_retornos",
            service_url=custodia_url_padrao(),
            broker_url=broker_url_padrao(),
            handlers=HANDLERS,
            data_dir=data_dir,
        )

    return app


app = criar_custodia_app()
