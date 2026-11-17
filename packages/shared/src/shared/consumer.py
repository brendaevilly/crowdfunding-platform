
"""Registro de assinaturas e consumo idempotente de eventos."""

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from shared.db import transaction
from shared.idempotency import consume_once

logger = logging.getLogger(__name__)

EventHandler = Callable[[sqlite3.Connection, dict[str, Any]], None]


class EventEnvelope(BaseModel):
    """Envelope padrão de eventos."""

    model_config = ConfigDict(populate_by_name=True)

    eventId: str = Field(min_length=1)
    tipo: str = Field(min_length=1)
    versao: int = Field(default=1, ge=1, alias="versão")
    ocorridoEm: str = Field(min_length=1)
    correlationId: str | None = None
    payload: dict[str, Any]


class BrokerDelivery(BaseModel):
    """Formato utilizado pelo broker ao entregar um evento."""

    eventId: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    payload: dict[str, Any]
    correlationId: str | None = None


def register_subscriptions(
    service: str,
    service_url: str,
    broker_url: str,
    topics: list[str],
) -> None:
    """Registra os tópicos consumidos pelo serviço no broker."""
    endpoint = f"{broker_url.rstrip('/')}/subscriptions"
    subscriber_url = service_url.rstrip("/")

    for topic in topics:
        response = httpx.post(
            endpoint,
            json={
                "service": service,
                "topic": topic,
                "url": subscriber_url,
            },
            timeout=5.0,
        )
        response.raise_for_status()

        logger.info(
            "Assinatura registrada: serviço=%s tópico=%s",
            service,
            topic,
        )


def create_events_router(
    service: str,
    handlers: dict[str, EventHandler],
    data_dir: str | Path = "data",
) -> APIRouter:
    """Cria a rota POST /events com despacho por tópico."""
    router = APIRouter()

    @router.post("/events")
    def receive_event(delivery: BrokerDelivery) -> dict[str, str | bool]:
        handler = handlers.get(delivery.topic)

        if handler is None:
            raise HTTPException(
                status_code=404,
                detail=f"Tópico não registrado: {delivery.topic}",
            )

        try:
            envelope = EventEnvelope.model_validate(delivery.payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Envelope de evento inválido",
            ) from exc

        if envelope.eventId != delivery.eventId:
            raise HTTPException(
                status_code=422,
                detail="eventId da entrega não corresponde ao envelope",
            )

        if envelope.tipo != delivery.topic:
            raise HTTPException(
                status_code=422,
                detail="Tipo do evento não corresponde ao tópico",
            )

        def process(conn: sqlite3.Connection) -> bool:
            processed, _ = consume_once(
                envelope.eventId,
                conn,
                lambda tx: handler(tx, envelope.payload),
            )
            return processed

        try:
            processed = transaction(process, service, data_dir)
        except (sqlite3.Error, ValueError):
            logger.exception(
                "Erro ao processar evento %s",
                delivery.eventId,
            )
            raise HTTPException(
                status_code=500,
                detail="Falha ao processar evento",
            ) from None

        return {
            "eventId": delivery.eventId,
            "processed": processed,
        }

    return router
