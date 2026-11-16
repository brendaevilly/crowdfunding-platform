

"""Aplicação HTTP do broker local de mensagens."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from broker.dispatcher import dispatch_pending
from broker.dlq import router as dlq_router
from broker.publish import router as publish_router
from broker.stats import router as stats_router
from broker.subscriptions import router as subscriptions_router
from shared.db import migrate
from shared.http.app import create_app

logger = logging.getLogger(__name__)


async def run_dispatcher() -> None:
    """Executa periodicamente as entregas pendentes."""
    interval = max(
        1,
        int(os.getenv("BROKER_DISPATCH_INTERVAL", "2")),
    )

    while True:
        try:
            await asyncio.to_thread(dispatch_pending)
        except Exception:
            logger.exception("Erro ao executar dispatcher")

        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicia e encerra o dispatcher junto com o broker."""
    from pathlib import Path

    migrations_dir = (
        Path(__file__).resolve().parents[2] / "migrations"
    )
    migrate("broker", migrations_dir)

    task = asyncio.create_task(run_dispatcher())

    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = create_app("broker", version="0.1.0")
app.router.lifespan_context = lifespan

app.include_router(subscriptions_router)
app.include_router(publish_router)
app.include_router(dlq_router)
app.include_router(stats_router)
