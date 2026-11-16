
"""Cadastro de assinantes do broker."""

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from shared.db import migrate, open_db

router = APIRouter()

MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[2] / "migrations"
)


class SubscriptionRequest(BaseModel):
    service: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    url: str = Field(min_length=1)


@router.post("/subscriptions", status_code=201)
def create_subscription(data: SubscriptionRequest):
    migrate("broker", MIGRATIONS_DIR)

    with open_db("broker") as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO broker_subscriptions
                (service, topic, url)
            VALUES (?, ?, ?)
            """,
            (data.service, data.topic, data.url),
        )

        created = cursor.rowcount == 1

    return {
        "service": data.service,
        "topic": data.topic,
        "url": data.url,
        "created": created,
    }
