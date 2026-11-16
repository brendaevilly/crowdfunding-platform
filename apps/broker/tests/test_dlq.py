
"""Testes da DLQ e do replay de entregas."""

from contextlib import closing

import httpx
from fastapi.testclient import TestClient

from broker.app import app
from broker.dispatcher import dispatch_pending
from shared.db import open_db


def test_dlq_e_replay(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROKER_MAX_ATTEMPTS", "2")

    def fake_failure(url, json, timeout):
        raise httpx.ConnectError("Serviço indisponível")

    monkeypatch.setattr(httpx, "post", fake_failure)

    client = TestClient(app)

    assinatura = {
        "service": "notificacao",
        "topic": "AporteConfirmado",
        "url": "http://localhost:3005",
    }
    assert client.post(
        "/subscriptions", json=assinatura
    ).status_code == 201

    evento = {
        "eventId": "evento-dlq-001",
        "topic": "AporteConfirmado",
        "payload": {"aporteId": "aporte-123"},
        "correlationId": "correlation-001",
    }
    assert client.post(
        "/publish", json=evento
    ).status_code == 201

    # Primeira tentativa: falha e agenda retry.
    assert dispatch_pending() == 0

    # Libera a próxima tentativa sem esperar.
    with closing(open_db("broker")) as conn:
        conn.execute(
            """
            UPDATE broker_deliveries
            SET next_attempt_at = NULL
            """
        )
        conn.commit()

    # Segunda tentativa: atinge o limite e entra na DLQ.
    assert dispatch_pending() == 0

    resposta = client.get("/dlq")
    assert resposta.status_code == 200

    mensagens = resposta.json()
    assert len(mensagens) == 1
    assert mensagens[0]["attempts"] == 2

    delivery_id = mensagens[0]["id"]

    # Recoloca a entrega na fila.
    resposta = client.post(
        f"/dlq/{delivery_id}/replay"
    )
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "pending"

    # O serviço volta a funcionar.
    def fake_success(url, json, timeout):
        request = httpx.Request("POST", url)
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx, "post", fake_success)

    assert dispatch_pending() == 1

    with closing(open_db("broker")) as conn:
        status, attempts = conn.execute(
            """
            SELECT status, attempts
            FROM broker_deliveries
            WHERE id = ?
            """,
            (delivery_id,),
        ).fetchone()

    assert status == "delivered"
    assert attempts == 1
    assert client.get("/dlq").json() == []
