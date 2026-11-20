"""Aplicação FastAPI do microsserviço Campanhas."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from campanhas.api import criar_campanhas_router
from campanhas.config import broker_url_padrao, campanhas_url_padrao
from campanhas.consumidores_custodia import (
    consumir_resultado_campanha,
    consumir_total_arrecadado_atualizado,
)
from campanhas.repository import inicializar_banco
from campanhas.usuarios_cache import (
    consumir_usuario_cadastrado,
    consumir_usuario_status_alterado,
)
from contracts.topicos import (
    RESULTADO_CAMPANHA,
    TOTAL_ARRECADADO_ATUALIZADO,
    USUARIO_CADASTRADO,
    USUARIO_STATUS_ALTERADO,
)
from shared.consumer import EventHandler
from shared.http.app import create_app
from shared.messaging import configure_messaging

logger = logging.getLogger(__name__)

HANDLERS: dict[str, EventHandler] = {
    USUARIO_CADASTRADO: consumir_usuario_cadastrado,
    USUARIO_STATUS_ALTERADO: consumir_usuario_status_alterado,
    TOTAL_ARRECADADO_ATUALIZADO: consumir_total_arrecadado_atualizado,
    RESULTADO_CAMPANHA: consumir_resultado_campanha,
}


def criar_campanhas_app(data_dir: str | Path = "data") -> FastAPI:
    """Fábrica da aplicação FastAPI de Gestão de Campanhas."""
    app = create_app("campanhas", version="0.1.0")

    rotas = criar_campanhas_router(data_dir)
    app.include_router(rotas)
    app.include_router(rotas, prefix="/campanhas")

    @asynccontextmanager
    async def campanhas_lifespan(application: FastAPI) -> AsyncIterator[None]:
        inicializar_banco(data_dir)
        logger.info("Banco de Campanhas inicializado com sucesso.")
        yield

    app.router.lifespan_context = campanhas_lifespan

    habilitar_messaging = os.getenv("CAMPANHAS_MESSAGING_ENABLED", "true").lower() in (
        "true",
        "1",
        "yes",
    )

    if habilitar_messaging:
        configure_messaging(
            app,
            service="campanhas",
            service_url=campanhas_url_padrao(),
            broker_url=broker_url_padrao(),
            handlers=HANDLERS,
            data_dir=data_dir,
        )

    return app


app = criar_campanhas_app()
