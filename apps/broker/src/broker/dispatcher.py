"""Entrega de eventos aos assinantes do broker."""

import json
import logging
import os
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import httpx

from broker.retry import max_attempts, next_attempt_at
from shared.db import transaction

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Retorna a data e hora atual em UTC."""
    return datetime.now(UTC)


def db_timestamp(value: datetime) -> str:
    """Converte uma data para o formato usado no SQLite."""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def lease_seconds() -> int:
    """Tempo de reserva de uma entrega."""
    return max(
        10,
        int(os.getenv("BROKER_LEASE_SECONDS", "30")),
    )


def reserve_delivery(
    conn: sqlite3.Connection,
    excluded_ids: set[int] | None = None,
) -> tuple[Any, ...] | None:
    """Reserva atomicamente uma entrega disponível."""
    now = db_timestamp(utc_now())
    excluded_ids = excluded_ids or set()

    rows = conn.execute(
        """
        SELECT
            d.id,
            d.attempts,
            e.event_id,
            e.topic,
            e.payload,
            e.correlation_id,
            s.url
        FROM broker_deliveries AS d
        JOIN broker_events AS e
            ON e.id = d.event_id
        JOIN broker_subscriptions AS s
            ON s.id = d.subscription_id
        WHERE (
            d.status = 'pending'
            AND (
                d.next_attempt_at IS NULL
                OR d.next_attempt_at <= ?
            )
        )
        OR (
            d.status = 'processing'
            AND d.next_attempt_at <= ?
        )
        ORDER BY d.id
        """,
        (now, now),
    ).fetchall()

    row = next(
        (item for item in rows if item[0] not in excluded_ids),
        None,
    )

    if row is None:
        return None

    token = str(uuid.uuid4())
    expires_at = db_timestamp(utc_now() + timedelta(seconds=lease_seconds()))

    conn.execute(
        """
        UPDATE broker_deliveries
        SET status = 'processing',
            next_attempt_at = ?,
            lease_token = ?
        WHERE id = ?
        """,
        (expires_at, token, row[0]),
    )

    return (*row, token)


def mark_failure(
    conn: sqlite3.Connection,
    delivery_id: int,
    token: str,
    attempts: int,
    exhausted: bool,
    error_message: str,
) -> bool:
    """Registra falha e agenda retry ou envia para a DLQ."""
    cursor = conn.execute(
        """
        UPDATE broker_deliveries
        SET attempts = ?,
            status = ?,
            next_attempt_at = ?,
            last_error = ?,
            lease_token = NULL
        WHERE id = ?
          AND status = 'processing'
          AND lease_token = ?
        """,
        (
            attempts,
            "dlq" if exhausted else "pending",
            None if exhausted else next_attempt_at(attempts),
            error_message,
            delivery_id,
            token,
        ),
    )
    return cursor.rowcount == 1


def mark_delivered(
    conn: sqlite3.Connection,
    delivery_id: int,
    token: str,
) -> bool:
    """Confirma uma entrega somente se a reserva ainda for válida."""
    cursor = conn.execute(
        """
        UPDATE broker_deliveries
        SET status = 'delivered',
            attempts = attempts + 1,
            next_attempt_at = NULL,
            delivered_at = CURRENT_TIMESTAMP,
            last_error = NULL,
            lease_token = NULL
        WHERE id = ?
          AND status = 'processing'
          AND lease_token = ?
        """,
        (delivery_id, token),
    )
    return cursor.rowcount == 1


def dispatch_pending() -> int:
    """Processa entregas disponíveis com reserva SQLite."""
    delivered = 0
    processed: set[int] = set()

    while True:
        delivery = transaction(
            partial(reserve_delivery, excluded_ids=processed),
            "broker",
        )

        if delivery is None:
            break

        (
            delivery_id,
            attempts,
            event_id,
            topic,
            payload,
            correlation_id,
            url,
            token,
        ) = delivery

        processed.add(delivery_id)

        body = {
            "eventId": event_id,
            "topic": topic,
            "payload": json.loads(payload),
            "correlationId": correlation_id,
        }

        try:
            response = httpx.post(
                f"{url.rstrip('/')}/events",
                json=body,
                timeout=5.0,
            )

            if not 200 <= response.status_code < 300:
                raise httpx.HTTPStatusError(
                    (f"Entrega não confirmada: HTTP {response.status_code}"),
                    request=response.request,
                    response=response,
                )

        except httpx.HTTPError as exc:
            new_attempts = attempts + 1
            exhausted = new_attempts >= max_attempts()
            error_message = str(exc)

            updated = transaction(
                partial(
                    mark_failure,
                    delivery_id=delivery_id,
                    token=token,
                    attempts=new_attempts,
                    exhausted=exhausted,
                    error_message=error_message,
                ),
                "broker",
            )

            if updated:
                if exhausted:
                    logger.error(
                        "ALERTA DLQ: evento %s atingiu %s tentativas",
                        event_id,
                        new_attempts,
                    )
                else:
                    logger.warning(
                        "Falha ao entregar evento %s: %s",
                        event_id,
                        error_message,
                    )

            continue

        updated = transaction(
            partial(
                mark_delivered,
                delivery_id=delivery_id,
                token=token,
            ),
            "broker",
        )

        if updated:
            delivered += 1

    return delivered
