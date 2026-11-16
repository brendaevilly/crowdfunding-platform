
"""Estatísticas das entregas do broker."""

from contextlib import closing
from pathlib import Path

from fastapi import APIRouter

from shared.db import migrate, open_db

router = APIRouter()

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


@router.get("/stats")
def get_stats():
    """Retorna estatísticas de entregas por tópico."""
    migrate("broker", MIGRATIONS_DIR)

    with closing(open_db("broker")) as conn:
        rows = conn.execute(
            """
            SELECT
                e.topic,
                CASE
                    WHEN d.status IN ('pending', 'processing')
                        THEN 'pending'
                    ELSE d.status
                END AS delivery_status,
                COUNT(*) AS total
            FROM broker_deliveries AS d
            JOIN broker_events AS e
                ON e.id = d.event_id
            GROUP BY
                e.topic,
                delivery_status
            ORDER BY
                e.topic,
                delivery_status
            """
        ).fetchall()

    stats = {}

    for topic, status, total in rows:
        if topic not in stats:
            stats[topic] = {
                "pending": 0,
                "delivered": 0,
                "dlq": 0,
            }

        stats[topic][status] = total

    return {"topics": stats}
