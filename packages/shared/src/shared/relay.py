"""Publicação de eventos pendentes da outbox no broker."""

import json
import logging
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from functools import partial
from pathlib import Path

import httpx

from shared.db import open_db, transaction

logger = logging.getLogger(__name__)


def pending_events(
    service: str,
    data_dir: str | Path = "data",
    limit: int = 100,
) -> list[tuple[str, str, str]]:
    """Consulta eventos pendentes no banco do serviço."""
    with closing(open_db(service, data_dir)) as conn:
        rows = conn.execute(
            """
            SELECT outbox_id, tipo_evento, payload
            FROM outbox_evento
            WHERE status = 'PENDENTE'
            ORDER BY created_at, outbox_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [(row[0], row[1], row[2]) for row in rows]


def mark_published(
    conn: sqlite3.Connection,
    outbox_id: str,
) -> bool:
    """Marca evento como publicado após confirmação do broker."""
    cursor = conn.execute(
        """
        UPDATE outbox_evento
        SET status = 'PUBLICADO',
            published_at = CURRENT_TIMESTAMP
        WHERE outbox_id = ?
          AND status = 'PENDENTE'
        """,
        (outbox_id,),
    )
    return cursor.rowcount == 1


def publish_pending(
    service: str,
    broker_url: str,
    data_dir: str | Path = "data",
    limit: int = 100,
) -> int:
    """Envia eventos pendentes e confirma somente após HTTP 2xx."""
    published = 0

    for outbox_id, topic, payload_json in pending_events(
        service,
        data_dir,
        limit,
    ):
        envelope = json.loads(payload_json)

        request_body = {
            "eventId": envelope["eventId"],
            "topic": topic,
            "payload": envelope,
            "correlationId": envelope.get("correlationId"),
        }

        try:
            response = httpx.post(
                f"{broker_url.rstrip('/')}/publish",
                json=request_body,
                timeout=5.0,
            )
            response.raise_for_status()
        except (httpx.HTTPError, ValueError):
            logger.exception(
                "Falha ao publicar evento %s no broker",
                outbox_id,
            )
            continue

        confirm = partial(mark_published, outbox_id=outbox_id)

        if transaction(confirm, service, data_dir):
            published += 1

    return published


def run_relay(
    service: str,
    broker_url: str,
    data_dir: str | Path = "data",
    interval: float = 0.5,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Executa periodicamente a publicação da outbox."""
    if interval <= 0:
        raise ValueError("Intervalo deve ser positivo")

    while should_stop is None or not should_stop():
        try:
            publish_pending(
                service=service,
                broker_url=broker_url,
                data_dir=data_dir,
            )
        except (sqlite3.Error, OSError, ValueError):
            logger.exception(
                "Erro no relay da outbox do serviço %s",
                service,
            )

        time.sleep(interval)
