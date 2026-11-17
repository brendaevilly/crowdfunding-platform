
"""Persistência de eventos na outbox transacional."""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class OutboxEvent:
    """Evento que será armazenado na outbox."""

    agregado_id: str
    tipo_evento: str
    payload: dict[str, Any]
    correlation_id: str
    versao: int = 1
    event_id: str | None = None


def add(
    tx: sqlite3.Connection,
    evento: OutboxEvent,
) -> str:
    """Registra um evento na mesma transação do estado de negócio.

    A função não executa commit. A transação externa é responsável
    por confirmar ou desfazer tanto o estado quanto o evento.
    """
    event_id = evento.event_id or str(uuid.uuid4())

    envelope = {
        "eventId": event_id,
        "tipo": evento.tipo_evento,
        "versão": evento.versao,
        "ocorridoEm": datetime.now(UTC).isoformat(),
        "correlationId": evento.correlation_id,
        "payload": evento.payload,
    }

    tx.execute(
        """
        INSERT INTO outbox_evento (
            outbox_id,
            agregado_id,
            tipo_evento,
            payload,
            status
        )
        VALUES (?, ?, ?, ?, 'PENDENTE')
        """,
        (
            event_id,
            evento.agregado_id,
            evento.tipo_evento,
            json.dumps(envelope, ensure_ascii=False),
        ),
    )

    return event_id
