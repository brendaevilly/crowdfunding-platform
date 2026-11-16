
"""Teste de retomada de entregas após reinicialização."""

from contextlib import closing

import httpx
from fastapi.testclient import TestClient

from broker.app import app
from shared.db import open_db


def test_retomada_apos_reinicializacao(tmp_path, monkeypatch):
    """Uma entrega pendente deve sobreviver ao reinício do broker."""
    monkeypatch.chdir(tmp_path)

    # Primeiro ciclo: salva o evento, sem executar o dispatcher.
    monkeypatch.setenv("BROKER_DISPATCH_ENABLED", "false")

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
            "eventId": "evento-restart-001",
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

    # A primeira instância foi encerrada.
    # A entrega precisa continuar registrada no SQLite.
    with closing(open_db("broker")) as conn:
        status = conn.execute(
            """
            SELECT status
            FROM broker_deliveries
            """
        ).fetchone()[0]

    assert status == "pending"

    chamadas = []

    def fake_post(url, json, timeout):
        chamadas.append(json["eventId"])

        request = httpx.Request("POST", url)
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)

    # Segundo ciclo: simula uma nova inicialização do broker.
    # O dispatcher automático deve recuperar a entrega.
    monkeypatch.setenv("BROKER_DISPATCH_ENABLED", "true")
    monkeypatch.setenv("BROKER_DISPATCH_INTERVAL", "1")

    with TestClient(app):
        # Aguarda o dispatcher concluir a entrega.
        import time

        limite = time.monotonic() + 5

        while time.monotonic() < limite:
            with closing(open_db("broker")) as conn:
                status = conn.execute(
                    """
                    SELECT status
                    FROM broker_deliveries
                    """
                ).fetchone()[0]

            if status == "delivered":
                break

            time.sleep(0.1)

    assert status == "delivered"
    assert chamadas == ["evento-restart-001"]
