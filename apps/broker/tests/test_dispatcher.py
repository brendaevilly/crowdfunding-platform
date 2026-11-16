"""Testes das entregas de eventos do broker."""

from contextlib import closing

import httpx
from fastapi.testclient import TestClient

from broker.app import app
from broker.dispatcher import dispatch_pending
from shared.db import open_db


def preparar_evento(client):
    """Cadastra um assinante e publica um evento."""
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
        "eventId": "evento-001",
        "topic": "AporteConfirmado",
        "payload": {"aporteId": "aporte-123"},
        "correlationId": "correlation-001",
    }

    resposta = client.post(
        "/publish",
        json=evento,
    )
    assert resposta.status_code == 201


def test_dispatcher_entrega_com_sucesso(tmp_path, monkeypatch):
    """Confirma entrega quando o assinante responde HTTP 2xx."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROKER_DISPATCH_ENABLED", "false")

    def fake_post(url, json, timeout):
        assert url == "http://localhost:3005/events"
        assert json["eventId"] == "evento-001"
        assert json["topic"] == "AporteConfirmado"
        assert json["payload"]["aporteId"] == "aporte-123"
        assert json["correlationId"] == "correlation-001"

        request = httpx.Request("POST", url)
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)

    with TestClient(app) as client:
        preparar_evento(client)

        entregues = dispatch_pending()

        assert entregues == 1

    with closing(open_db("broker")) as conn:
        status, attempts, lease_token = conn.execute(
            """
            SELECT status, attempts, lease_token
            FROM broker_deliveries
            """
        ).fetchone()

    assert status == "delivered"
    assert attempts == 1
    assert lease_token is None


def test_dispatcher_agenda_retry(tmp_path, monkeypatch):
    """Agenda uma nova tentativa quando o assinante falha."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROKER_DISPATCH_ENABLED", "false")
    monkeypatch.setenv("BROKER_MAX_ATTEMPTS", "5")

    def fake_post(url, json, timeout):
        raise httpx.ConnectError("Serviço indisponível")

    monkeypatch.setattr(httpx, "post", fake_post)

    with TestClient(app) as client:
        preparar_evento(client)

        entregues = dispatch_pending()

        assert entregues == 0

    with closing(open_db("broker")) as conn:
        (
            status,
            attempts,
            next_attempt,
            last_error,
            lease_token,
        ) = conn.execute(
            """
            SELECT
                status,
                attempts,
                next_attempt_at,
                last_error,
                lease_token
            FROM broker_deliveries
            """
        ).fetchone()

    assert status == "pending"
    assert attempts == 1
    assert next_attempt is not None
    assert "Serviço indisponível" in last_error
    assert lease_token is None
