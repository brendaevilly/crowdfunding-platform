"""Registro de assinaturas e consumo idempotente de eventos."""

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from contracts.catalogo import ContratoInvalido, ler_envelope
from shared.correlation import (
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from shared.db import transaction
from shared.idempotency import consume_once
from shared.resilience import Bulkhead

logger = logging.getLogger(__name__)

EventHandler = Callable[[sqlite3.Connection, dict[str, Any]], None]


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
    max_concurrent_per_topic: int = 5,
) -> APIRouter:
    """Cria POST /events com validação de contratos e Bulkhead por tópico."""
    if max_concurrent_per_topic < 1:
        raise ValueError("max_concurrent_per_topic deve ser positivo")

    router = APIRouter()

    bulkheads = {topic: Bulkhead(max_concurrent=max_concurrent_per_topic) for topic in handlers}

    @router.post("/events")
    async def receive_event(
        delivery: BrokerDelivery,
    ) -> dict[str, str | bool]:
        handler = handlers.get(delivery.topic)

        if handler is None:
            raise HTTPException(
                status_code=422,
                detail=f"Contrato de evento inválido: tópico não registrado: {delivery.topic}",
            )

        dados_legados = delivery.payload

        try:
            if dados_legados.get("tipo") != delivery.topic:
                raise ContratoInvalido("Tipo do evento não corresponde ao tópico da entrega")

            envelope_oficial = {
                "eventId": dados_legados["eventId"],
                "topic": delivery.topic,
                "schemaVersion": dados_legados.get(
                    "versão",
                    dados_legados.get("versao", 1),
                ),
                "occurredAt": dados_legados["ocorridoEm"],
                "correlationId": (
                    delivery.correlationId
                    or dados_legados.get("correlationId")
                    or get_correlation_id()
                    or delivery.eventId
                ),
                "payload": dados_legados["payload"],
            }

            envelope = ler_envelope(envelope_oficial)

            if envelope.event_id != delivery.eventId:
                raise ContratoInvalido("eventId da entrega não corresponde ao envelope")

        except (ContratoInvalido, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Contrato rejeitado: serviço=%s tópico=%s evento=%s motivo=%s",
                service,
                delivery.topic,
                delivery.eventId,
                exc,
            )
            raise HTTPException(
                status_code=422,
                detail=f"Contrato de evento inválido: {exc}",
            ) from exc

        cid = delivery.correlationId or envelope.correlation_id or get_correlation_id()
        token = set_correlation_id(cid) if cid else None

        def process(conn: sqlite3.Connection) -> bool:
            processed, _ = consume_once(
                envelope.event_id,
                conn,
                lambda tx: handler(
                    tx,
                    envelope.payload.model_dump(
                        by_alias=True,
                        mode="json",
                    ),
                ),
            )
            return processed

        def execute_transaction() -> bool:
            return transaction(process, service, data_dir)

        async def process_event() -> bool:
            return await asyncio.to_thread(execute_transaction)

        try:
            processed = await bulkheads[delivery.topic].call(process_event)
        except Exception:
            logger.exception(
                "Erro ao processar evento %s",
                delivery.eventId,
            )
            raise HTTPException(
                status_code=500,
                detail="Falha ao processar evento",
            ) from None
        finally:
            if token is not None:
                reset_correlation_id(token)

        return {
            "eventId": delivery.eventId,
            "processed": processed,
        }

    return router
