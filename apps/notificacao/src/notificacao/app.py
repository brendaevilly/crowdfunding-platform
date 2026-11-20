"""Aplicação FastAPI do microsserviço Notificação."""

from __future__ import annotations

import logging
import os
import threading
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
from notificacao.ttl import run_ttl_cleaner
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
    app.include_router(rotas, prefix="/notificacoes")

    habilitar_ttl = os.getenv("NOTIFICACAO_TTL_ENABLED", "true").lower() in (
        "true",
        "1",
        "yes",
    )

    @asynccontextmanager
    async def notificacao_lifespan(application: FastAPI) -> AsyncIterator[None]:
        inicializar_banco(data_dir)
        logger.info("Banco de Notificação inicializado com sucesso.")

        stop_event = threading.Event()
        ttl_thread: threading.Thread | None = None

        if habilitar_ttl:
            ttl_thread = threading.Thread(
                target=run_ttl_cleaner,
                kwargs={
                    "data_dir": data_dir,
                    "should_stop": stop_event.is_set,
                },
                daemon=True,
                name="notificacao-ttl-cleaner",
            )
            ttl_thread.start()

        try:
            yield
        finally:
            if ttl_thread is not None:
                stop_event.set()
                ttl_thread.join(timeout=3.0)

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
