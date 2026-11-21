"""Testes da DLQ e do replay de entregas."""

from contextlib import closing

import httpx
from fastapi.testclient import TestClient

from broker.app import app
from broker.dispatcher import dispatch_pending
from shared.db import open_db


def test_dlq_e_replay(tmp_path, monkeypatch):
    """Testa falhas, envio para DLQ e recuperação."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROKER_DISPATCH_ENABLED", "false")
    monkeypatch.setenv("BROKER_MAX_ATTEMPTS", "2")

    def fake_failure(url, json, timeout):
        raise httpx.ConnectError("Serviço indisponível")

    monkeypatch.setattr(httpx, "post", fake_failure)

    assinatura = {
        "service": "notificacao",
        "topic": "AporteConfirmado",
        "url": "http://localhost:3005",
    }

    evento = {
        "eventId": "evento-dlq-001",
        "topic": "AporteConfirmado",
        "payload": {"aporteId": "aporte-123"},
        "correlationId": "correlation-001",
    }

    with TestClient(app) as client:
        resposta = client.post(
            "/subscriptions",
            json=assinatura,
        )
        assert resposta.status_code == 201

        resposta = client.post(
            "/publish",
            json=evento,
        )
        assert resposta.status_code == 201

        # Primeira tentativa: falha e agenda retry.
        assert dispatch_pending() == 0

        with closing(open_db("broker")) as conn:
            status, attempts, lease_token = conn.execute(
                """
                SELECT status, attempts, lease_token
                FROM broker_deliveries
                """
            ).fetchone()

        assert status == "pending"
        assert attempts == 1
        assert lease_token is None

        # Libera a próxima tentativa sem esperar.
        with closing(open_db("broker")) as conn:
            conn.execute(
                """
                UPDATE broker_deliveries
                SET next_attempt_at = NULL
                WHERE status = 'pending'
                """
            )
            conn.commit()

        # Segunda tentativa: atinge o limite e entra na DLQ.
        assert dispatch_pending() == 0

        resposta = client.get("/dlq")
        assert resposta.status_code == 200

        mensagens = resposta.json()

        assert len(mensagens) == 1
        assert mensagens[0]["eventId"] == "evento-dlq-001"
        assert mensagens[0]["attempts"] == 2
        assert "Serviço indisponível" in mensagens[0]["lastError"]

        delivery_id = mensagens[0]["id"]

        with closing(open_db("broker")) as conn:
            status, lease_token = conn.execute(
                """
                SELECT status, lease_token
                FROM broker_deliveries
                WHERE id = ?
                """,
                (delivery_id,),
            ).fetchone()

        assert status == "dlq"
        assert lease_token is None

        # Recoloca a entrega na fila.
        resposta = client.post(f"/dlq/{delivery_id}/replay")

        assert resposta.status_code == 200
        assert resposta.json()["status"] == "pending"
        assert resposta.json()["replayed"] is True

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
                WHERE id = ?
                """,
                (delivery_id,),
            ).fetchone()

        assert status == "pending"
        assert attempts == 0
        assert next_attempt is None
        assert last_error is None
        assert lease_token is None

        # O serviço volta a funcionar.
        def fake_success(url, json, timeout):
            request = httpx.Request("POST", url)
            return httpx.Response(200, request=request)

        monkeypatch.setattr(httpx, "post", fake_success)

        assert dispatch_pending() == 1

        with closing(open_db("broker")) as conn:
            status, attempts, lease_token = conn.execute(
                """
                SELECT status, attempts, lease_token
                FROM broker_deliveries
                WHERE id = ?
                """,
                (delivery_id,),
            ).fetchone()

        assert status == "delivered"
        assert attempts == 1
        assert lease_token is None

        assert client.get("/dlq").json() == []


def test_rejeicao_de_contrato_422_vai_para_dlq(
    tmp_path,
    monkeypatch,
):
    """Rejeição HTTP 422 deve chegar à DLQ com o motivo."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROKER_DISPATCH_ENABLED", "false")
    monkeypatch.setenv("BROKER_MAX_ATTEMPTS", "1")

    def fake_invalid(url, json, timeout):
        request = httpx.Request("POST", url)
        return httpx.Response(
            422,
            request=request,
            text='{"detail":"Contrato de evento inválido: aporteId ausente"}',
        )

    monkeypatch.setattr(httpx, "post", fake_invalid)

    assinatura = {
        "service": "aportes",
        "topic": "aporte.confirmado",
        "url": "http://localhost:3002",
    }

    evento = {
        "eventId": "evento-contrato-invalido",
        "topic": "aporte.confirmado",
        "payload": {},
        "correlationId": "correlation-contrato",
    }

    with TestClient(app) as client:
        resposta = client.post("/subscriptions", json=assinatura)
        assert resposta.status_code == 201

        resposta = client.post("/publish", json=evento)
        assert resposta.status_code == 201

        assert dispatch_pending() == 0

        resposta = client.get("/dlq")
        assert resposta.status_code == 200

        mensagens = resposta.json()
        assert len(mensagens) == 1
        assert mensagens[0]["eventId"] == "evento-contrato-invalido"
        assert mensagens[0]["attempts"] == 1
        assert "HTTP 422" in mensagens[0]["lastError"]
        assert "Contrato de evento inválido" in mensagens[0]["lastError"]
