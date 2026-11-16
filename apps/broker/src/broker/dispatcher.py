
"""Entrega de eventos aos assinantes do broker."""

import json
import logging
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone

import httpx

from broker.retry import max_attempts, next_attempt_at
from shared.db import open_db, transaction

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def db_timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def lease_seconds() -> int:
    """Tempo de reserva de uma entrega."""
    return max(
        10,
        int(os.getenv("BROKER_LEASE_SECONDS", "30")),
    )


def reserve_delivery(conn: sqlite3.Connection):
    """Reserva uma entrega disponível de forma atômica."""
    now = db_timestamp(utc_now())

    row = conn.execute(
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
        LIMIT 1
        """,
        (now, now),
    ).fetchone()

    if row is None:
        return None

    token = str(uuid.uuid4())
    expires_at = db_timestamp(
        utc_now() + timedelta(seconds=lease_seconds())
    )

    conn.execute(
        """
        UPDATE broker_deliveries
        SET status = 'processing',
            next_attempt_at = ?,
            last_error = ?
        WHERE id = ?
        """,
        (expires_at, token, row[0]),
    )

    return (*row, token)


def dispatch_pending() -> int:
    """Processa entregas disponíveis com reserva SQLite."""
    delivered = 0
    processed = set()

    while True:
        def reserve(conn):
            return reserve_delivery(conn)

        delivery = transaction(reserve, "broker")

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

        if delivery_id in processed:
            break

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
                    f"Entrega não confirmada: HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )

        except httpx.HTTPError as exc:
            new_attempts = attempts + 1
            exhausted = new_attempts >= max_attempts()

            def mark_failure(conn):
                conn.execute(
                    """
                    UPDATE broker_deliveries
                    SET attempts = ?,
                        status = ?,
                        next_attempt_at = ?,
                        last_error = ?
                    WHERE id = ?
                      AND status = 'processing'
                      AND last_error = ?
                    """,
                    (
                        new_attempts,
                        "dlq" if exhausted else "pending",
                        (
                            None
                            if exhausted
                            else next_attempt_at(new_attempts)
                        ),
                        str(exc),
                        delivery_id,
                        token,
                    ),
                )

            transaction(mark_failure, "broker")

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
                    exc,
                )

            continue

        def mark_delivered(conn):
            cursor = conn.execute(
                """
                UPDATE broker_deliveries
                SET status = 'delivered',
                    attempts = attempts + 1,
                    next_attempt_at = NULL,
                    delivered_at = CURRENT_TIMESTAMP,
                    last_error = NULL
                WHERE id = ?
                  AND status = 'processing'
                  AND last_error = ?
                """,
                (delivery_id, token),
            )
            return cursor.rowcount == 1

        if transaction(mark_delivered, "broker"):
            delivered += 1

    return delivered
