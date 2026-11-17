"""Teste de recuperação de assinante indisponível."""

from contextlib import closing

import httpx
from fastapi.testclient import TestClient

from broker.app import app
from broker.dispatcher import dispatch_pending
from shared.db import open_db


def test_assinante_offline_recebe_quando_volta(tmp_path, monkeypatch):
    """Entrega mensagem quando o assinante volta a funcionar."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROKER_DISPATCH_ENABLED", "false")
    monkeypatch.setenv("BROKER_MAX_ATTEMPTS", "3")

    chamadas = []

    def fake_offline(url, json, timeout):
        chamadas.append(json["eventId"])
        raise httpx.ConnectError("Assinante offline")

    monkeypatch.setattr(httpx, "post", fake_offline)

    with TestClient(app) as client:
        assinatura = {
            "service": "notificacao",
            "topic": "AporteConfirmado",
            "url": "http://localhost:3005",
        }

        resposta = client.post(
            "/subscriptions",
            json=assinatura,
        )
        assert resposta.status_code == 201

        evento = {
            "eventId": "evento-offline-001",
            "topic": "AporteConfirmado",
            "payload": {"aporteId": "aporte-123"},
            "correlationId": "correlation-001",
        }

        resposta = client.post(
            "/publish",
            json=evento,
        )
        assert resposta.status_code == 201
        assert resposta.json()["deliveries"] == 1

        # Primeira tentativa: assinante indisponível.
        assert dispatch_pending() == 0

        with closing(open_db("broker")) as conn:
            status, attempts, next_attempt = conn.execute(
                """
                SELECT status, attempts, next_attempt_at
                FROM broker_deliveries
                """
            ).fetchone()

        assert status == "pending"
        assert attempts == 1
        assert next_attempt is not None

        # Simula a passagem do intervalo de retry.
        with closing(open_db("broker")) as conn:
            conn.execute(
                """
                UPDATE broker_deliveries
                SET next_attempt_at = NULL
                WHERE status = 'pending'
                """
            )
            conn.commit()

        # O assinante volta a funcionar.
        def fake_online(url, json, timeout):
            chamadas.append(json["eventId"])

            request = httpx.Request("POST", url)
            return httpx.Response(200, request=request)

        monkeypatch.setattr(httpx, "post", fake_online)

        # Segunda tentativa: entrega bem-sucedida.
        assert dispatch_pending() == 1

    with closing(open_db("broker")) as conn:
        status, attempts, lease_token = conn.execute(
            """
            SELECT status, attempts, lease_token
            FROM broker_deliveries
            """
        ).fetchone()

        total_eventos = conn.execute("SELECT COUNT(*) FROM broker_events").fetchone()[0]

        total_entregas = conn.execute("SELECT COUNT(*) FROM broker_deliveries").fetchone()[0]

    assert status == "delivered"
    assert attempts == 2
    assert lease_token is None
    assert total_eventos == 1
    assert total_entregas == 1
    assert chamadas == [
        "evento-offline-001",
        "evento-offline-001",
    ]
