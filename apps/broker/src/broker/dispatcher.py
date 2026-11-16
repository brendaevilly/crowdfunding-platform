
"""Entrega de eventos aos assinantes do broker."""

import json
import logging
from contextlib import closing

import httpx

from broker.retry import max_attempts, next_attempt_at
from shared.db import open_db, transaction

logger = logging.getLogger(__name__)


def dispatch_pending() -> int:
    """Processa uma rodada de entregas pendentes."""

    with closing(open_db("broker")) as conn:
        deliveries = conn.execute(
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
            WHERE d.status = 'pending'
              AND (
                  d.next_attempt_at IS NULL
                  OR d.next_attempt_at <= CURRENT_TIMESTAMP
              )
            ORDER BY d.id
            """
        ).fetchall()

    delivered = 0

    for delivery in deliveries:
        (
            delivery_id,
            attempts,
            event_id,
            topic,
            payload,
            correlation_id,
            url,
        ) = delivery

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
            response.raise_for_status()

        except httpx.HTTPError as exc:
            new_attempts = attempts + 1
            exhausted = new_attempts >= max_attempts()

            if exhausted:
                logger.error(
                    "ALERTA DLQ: evento %s atingiu %s tentativas",
                    event_id,
                    new_attempts,
                )
            else:
                logger.warning(
                    "Falha ao entregar evento %s "
                    "(tentativa %s): %s",
                    event_id,
                    new_attempts,
                    exc,
                )

            def mark_failure(conn):
                conn.execute(
                    """
                    UPDATE broker_deliveries
                    SET attempts = ?,
                        status = ?,
                        next_attempt_at = ?,
                        last_error = ?
                    WHERE id = ?
                      AND status = 'pending'
                    """,
                    (
                        new_attempts,
                        "dlq" if exhausted else "pending",
                        None
                        if exhausted
                        else next_attempt_at(new_attempts),
                        str(exc),
                        delivery_id,
                    ),
                )

            transaction(mark_failure, "broker")
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
                  AND status = 'pending'
                """,
                (delivery_id,),
            )
            return cursor.rowcount == 1

        if transaction(mark_delivered, "broker"):
            delivered += 1

    return delivered
