"""Cadastro de assinantes do broker."""

import sqlite3
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from shared.db import migrate, transaction

router = APIRouter()

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class SubscriptionRequest(BaseModel):
    service: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    url: str = Field(min_length=1)


@router.post("/subscriptions", status_code=201)
def create_subscription(data: SubscriptionRequest) -> dict[str, str | bool]:
    """Cadastra um assinante sem criar registros duplicados."""
    migrate("broker", MIGRATIONS_DIR)

    def save_subscription(conn: sqlite3.Connection) -> bool:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO broker_subscriptions
                (service, topic, url)
            VALUES (?, ?, ?)
            """,
            (
                data.service,
                data.topic,
                data.url,
            ),
        )

        return cursor.rowcount == 1

    created = transaction(save_subscription, "broker")

    return {
        "service": data.service,
        "topic": data.topic,
        "url": data.url,
        "created": created,
    }
