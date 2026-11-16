
"""Consulta e recuperação de entregas da DLQ."""

from pathlib import Path

from fastapi import APIRouter, HTTPException

from shared.db import migrate, open_db, transaction

router = APIRouter()

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


@router.get("/dlq")
def list_dlq():
    """Lista entregas que atingiram o limite de tentativas."""
    migrate("broker", MIGRATIONS_DIR)

    conn = open_db("broker")

    try:
        rows = conn.execute(
            """
            SELECT
                d.id,
                e.event_id,
                e.topic,
                s.service,
                s.url,
                d.attempts,
                d.last_error
            FROM broker_deliveries AS d
            JOIN broker_events AS e
                ON e.id = d.event_id
            JOIN broker_subscriptions AS s
                ON s.id = d.subscription_id
            WHERE d.status = 'dlq'
            ORDER BY d.id
            """
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "id": row[0],
            "eventId": row[1],
            "topic": row[2],
            "service": row[3],
            "url": row[4],
            "attempts": row[5],
            "lastError": row[6],
        }
        for row in rows
    ]


@router.post("/dlq/{delivery_id}/replay")
def replay_dlq(delivery_id: int):
    """Recoloca uma entrega da DLQ na fila de processamento."""
    migrate("broker", MIGRATIONS_DIR)

    def replay(conn):
        cursor = conn.execute(
            """
            UPDATE broker_deliveries
            SET status = 'pending',
                attempts = 0,
                next_attempt_at = NULL,
                last_error = NULL,
                lease_token = NULL
            WHERE id = ?
              AND status = 'dlq'
            """,
            (delivery_id,),
        )

        return cursor.rowcount == 1

    if not transaction(replay, "broker"):
        raise HTTPException(
            status_code=404,
            detail="Entrega não encontrada na DLQ",
        )

    return {
        "id": delivery_id,
        "status": "pending",
        "replayed": True,
    }
