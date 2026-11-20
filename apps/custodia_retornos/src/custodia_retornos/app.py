"""Aplicação FastAPI do microsserviço Custódia e Retornos."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from contracts.topicos import APORTE_CONFIRMADO, CAMPANHA_PUBLICADA
from custodia_retornos.config import broker_url_padrao, custodia_url_padrao
from custodia_retornos.custodia.apuracao import apurar_pendentes
from custodia_retornos.custodia.clock import AdjustableClock, Clock, SystemClock
from custodia_retornos.custodia.consumidores import (
    consumir_aporte_confirmado,
    consumir_campanha_publicada,
)
from custodia_retornos.custodia.scheduler import executar_scheduler
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


class ClockAdvanceRequest(BaseModel):
    seconds: float = Field(gt=0)


def criar_custodia_app(
    data_dir: str | Path = "data",
    *,
    clock: Clock | None = None,
    dev_mode: bool | None = None,
    scheduler_enabled: bool = True,
) -> FastAPI:
    """Cria a aplicação FastAPI de Custódia e Retornos."""

    app = create_app("custodia_retornos", version="0.1.0")

    if dev_mode is None:
        dev_mode = os.getenv("CUSTODIA_DEV_MODE", "false").lower() in ("true", "1", "yes")

    if clock is None:
        clock = AdjustableClock() if dev_mode else SystemClock()

    relogio = clock

    if dev_mode:

        @app.post("/_dev/clock/advance")
        def advance_clock(request: ClockAdvanceRequest) -> dict[str, object]:
            if not isinstance(relogio, AdjustableClock):
                raise HTTPException(
                    status_code=409,
                    detail="Relógio não é ajustável",
                )
            agora = relogio.advance(request.seconds)
            quantidade = apurar_pendentes(relogio, data_dir)
            return {
                "now": agora.isoformat(),
                "apuradas": quantidade,
            }

    @asynccontextmanager
    async def custodia_lifespan(application: FastAPI) -> AsyncIterator[None]:
        migrate("custodia_retornos", MIGRATIONS_DIR, data_dir)
        install_messaging_schema("custodia_retornos", data_dir)
        logger.info("Migrations da Custódia aplicadas com sucesso.")
        tarefa = None
        if scheduler_enabled:
            tarefa = asyncio.create_task(
                executar_scheduler(relogio, data_dir),
                name="custodia-scheduler",
            )
        try:
            yield
        finally:
            if tarefa is not None:
                tarefa.cancel()
                await asyncio.gather(tarefa, return_exceptions=True)

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
