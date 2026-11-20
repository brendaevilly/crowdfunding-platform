"""Publicação de eventos no broker local."""

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from broker.rabbitmq import publish_to_rabbitmq
from shared.db import migrate, transaction

router = APIRouter()

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class PublishRequest(BaseModel):
    eventId: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    payload: dict[str, Any]
    correlationId: str | None = None


@router.post("/publish", status_code=201)
def publish_event(data: PublishRequest) -> dict[str, str | bool | int]:
    migrate("broker", MIGRATIONS_DIR)

    def save_event(conn: sqlite3.Connection) -> dict[str, str | bool | int]:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO broker_events
                (event_id, topic, payload, correlation_id)
            VALUES (?, ?, ?, ?)
            """,
            (
                data.eventId,
                data.topic,
                json.dumps(data.payload),
                data.correlationId,
            ),
        )

        if cursor.rowcount == 0:
            return {
                "eventId": data.eventId,
                "created": False,
                "deliveries": 0,
            }

        event_db_id = cursor.lastrowid

        subscribers = conn.execute(
            """
            SELECT id
            FROM broker_subscriptions
            WHERE topic = ?
            """,
            (data.topic,),
        ).fetchall()

        for (subscription_id,) in subscribers:
            conn.execute(
                """
                INSERT INTO broker_deliveries
                    (event_id, subscription_id)
                VALUES (?, ?)
                """,
                (event_db_id, subscription_id),
            )

        return {
            "eventId": data.eventId,
            "created": True,
            "deliveries": len(subscribers),
        }

    resultado = transaction(save_event, "broker")
    publish_to_rabbitmq(data.topic, data.eventId, data.payload, data.correlationId)
    return resultado
