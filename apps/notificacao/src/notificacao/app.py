"""Aplicação FastAPI do microsserviço Notificação."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from contracts.topicos import (
    APORTE_CONFIRMADO,
    IDENTIDADE_VERIFICADA,
    RESULTADO_CAMPANHA,
    RETORNO_DISTRIBUIDO,
)
from notificacao.api import criar_notificacao_router
from notificacao.config import broker_url_padrao, notificacao_url_padrao
from notificacao.consumidores import (
    consumir_aporte_confirmado,
    consumir_identidade_verificada,
    consumir_resultado_campanha,
    consumir_retorno_distribuido,
)
from notificacao.repository import inicializar_banco
from shared.consumer import EventHandler
from shared.http.app import create_app
from shared.messaging import configure_messaging

logger = logging.getLogger(__name__)

HANDLERS: dict[str, EventHandler] = {
    APORTE_CONFIRMADO: consumir_aporte_confirmado,
    RESULTADO_CAMPANHA: consumir_resultado_campanha,
    RETORNO_DISTRIBUIDO: consumir_retorno_distribuido,
    IDENTIDADE_VERIFICADA: consumir_identidade_verificada,
}


def criar_notificacao_app(data_dir: str | Path = "data") -> FastAPI:
    """Fábrica da aplicação FastAPI de Notificações."""
    app = create_app("notificacao", version="0.1.0")

    rotas = criar_notificacao_router(data_dir)
    app.include_router(rotas)
    app.include_router(rotas, prefix="/notificacao")

    @asynccontextmanager
    async def notificacao_lifespan(application: FastAPI) -> AsyncIterator[None]:
        inicializar_banco(data_dir)
        logger.info("Banco de Notificação inicializado com sucesso.")
        yield

    app.router.lifespan_context = notificacao_lifespan

    habilitar_messaging = os.getenv("NOTIFICACAO_MESSAGING_ENABLED", "true").lower() in (
        "true",
        "1",
        "yes",
    )

    if habilitar_messaging:
        configure_messaging(
            app,
            service="notificacao",
            service_url=notificacao_url_padrao(),
            broker_url=broker_url_padrao(),
            handlers=HANDLERS,
            data_dir=data_dir,
        )

    return app


app = criar_notificacao_app()
