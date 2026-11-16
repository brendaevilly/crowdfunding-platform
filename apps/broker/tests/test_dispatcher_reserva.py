
"""Testes de reserva e recuperação de entregas."""

from contextlib import closing

import httpx
from fastapi.testclient import TestClient

from broker.app import app
from broker.dispatcher import dispatch_pending, reserve_delivery
from shared.db import open_db, transaction


def preparar_evento(client):
    assinatura = {
        "service": "notificacao",
        "topic": "AporteConfirmado",
        "url": "http://localhost:3005",
    }
    assert client.post(
        "/subscriptions", json=assinatura
    ).status_code == 201

    evento = {
        "eventId": "evento-reserva-001",
        "topic": "AporteConfirmado",
        "payload": {"aporteId": "aporte-123"},
        "correlationId": "correlation-001",
    }
    assert client.post("/publish", json=evento).status_code == 201


def test_entrega_nao_pode_ser_reservada_duas_vezes(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    client = TestClient(app)
    preparar_evento(client)

    primeira = transaction(reserve_delivery, "broker")
    segunda = transaction(reserve_delivery, "broker")

    assert primeira is not None
    assert segunda is None

    with closing(open_db("broker")) as conn:
        status = conn.execute(
            "SELECT status FROM broker_deliveries"
        ).fetchone()[0]

    assert status == "processing"


def test_recupera_entrega_com_reserva_expirada(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    client = TestClient(app)
    preparar_evento(client)

    reserva = transaction(reserve_delivery, "broker")
    assert reserva is not None

    # Simula uma interrupção e a expiração da reserva.
    with closing(open_db("broker")) as conn:
        conn.execute(
            """
            UPDATE broker_deliveries
            SET next_attempt_at = '2000-01-01 00:00:00'
            WHERE status = 'processing'
            """
        )
        conn.commit()

    def fake_post(url, json, timeout):
        request = httpx.Request("POST", url)
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)

    assert dispatch_pending() == 1

    with closing(open_db("broker")) as conn:
        status = conn.execute(
            "SELECT status FROM broker_deliveries"
        ).fetchone()[0]

    assert status == "delivered"
