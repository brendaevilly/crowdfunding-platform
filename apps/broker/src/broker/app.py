"""Aplicação HTTP do broker local de mensagens."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse

from broker.dispatcher import dispatch_pending
from broker.dlq import router as dlq_router
from broker.painel import router as painel_router
from broker.publish import router as publish_router
from broker.stats import router as stats_router
from broker.subscriptions import router as subscriptions_router
from shared.db import migrate
from shared.http.app import create_app

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def dispatcher_enabled() -> bool:
    """Verifica se o dispatcher automático está habilitado."""
    return os.getenv("BROKER_DISPATCH_ENABLED", "true").lower() in ("true", "1", "yes")


async def run_dispatcher() -> None:
    """Executa periodicamente as entregas pendentes."""
    interval = max(
        1,
        int(os.getenv("BROKER_DISPATCH_INTERVAL", "2")),
    )

    while True:
        try:
            await asyncio.to_thread(dispatch_pending)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erro ao executar dispatcher")

        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Gerencia a inicialização e o encerramento do broker."""
    migrate("broker", MIGRATIONS_DIR)

    task: asyncio.Task[None] | None = None

    if dispatcher_enabled():
        task = asyncio.create_task(run_dispatcher())
        logger.info("Dispatcher automático iniciado")
    else:
        logger.info("Dispatcher automático desabilitado")

    try:
        yield
    finally:
        if task is not None:
            task.cancel()

            with suppress(asyncio.CancelledError):
                await task

            logger.info("Dispatcher automático encerrado")


app = create_app("broker", version="0.1.0")
app.router.lifespan_context = lifespan

app.include_router(subscriptions_router)
app.include_router(publish_router)
app.include_router(dlq_router)
app.include_router(stats_router)
app.include_router(painel_router)


@app.get("/", include_in_schema=False)
def root_broker(request: Request) -> Response:
    """Redireciona navegador para o painel ou devolve JSON com metadados."""
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url="/painel")

    return Response(
        content='{"service":"broker","version":"0.1.0","painel":"/painel"}',
        media_type="application/json",
    )
