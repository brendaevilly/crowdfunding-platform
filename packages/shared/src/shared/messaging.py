
"""Integração do messaging com o ciclo de vida do FastAPI."""

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI

from shared.consumer import EventHandler, create_events_router, register_subscriptions
from shared.relay import run_relay

logger = logging.getLogger(__name__)


def configure_messaging(
    app: FastAPI,
    *,
    service: str,
    service_url: str,
    broker_url: str,
    handlers: dict[str, EventHandler],
    data_dir: str | Path = "data",
) -> None:
    """Configura consumo e publicação de eventos de um serviço."""
    app.include_router(
        create_events_router(
            service=service,
            handlers=handlers,
            data_dir=data_dir,
        )
    )

    original_lifespan = app.router.lifespan_context

    @contextmanager
    def messaging_lifespan(application: FastAPI) -> Iterator[None]:
        stop_event = threading.Event()
        relay_thread = threading.Thread(
            target=run_relay,
            kwargs={
                "service": service,
                "broker_url": broker_url,
                "data_dir": data_dir,
                "should_stop": stop_event.is_set,
            },
            daemon=True,
            name=f"{service}-outbox-relay",
        )

        with original_lifespan(application):
            register_subscriptions(
                service=service,
                service_url=service_url,
                broker_url=broker_url,
                topics=list(handlers),
            )

            relay_thread.start()
            logger.info("Messaging iniciado: %s", service)

            try:
                yield
            finally:
                stop_event.set()
                relay_thread.join(timeout=6.0)
                logger.info("Messaging encerrado: %s", service)

    app.router.lifespan_context = messaging_lifespan
