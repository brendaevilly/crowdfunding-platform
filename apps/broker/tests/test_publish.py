
"""Testes da publicação de eventos do broker."""

from contextlib import closing

from fastapi.testclient import TestClient

from broker.app import app
from shared.db import open_db


def test_publish_cria_entregas_e_evita_duplicacao(
    tmp_path, monkeypatch
):
    """Publica um evento e evita entregas duplicadas."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROKER_DISPATCH_ENABLED", "false")

    assinatura = {
        "service": "notificacao",
        "topic": "AporteConfirmado",
        "url": "http://localhost:3005",
    }

    evento = {
        "eventId": "evento-001",
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

        primeira = client.post(
            "/publish",
            json=evento,
        )

        assert primeira.status_code == 201
        assert primeira.json()["created"] is True
        assert primeira.json()["deliveries"] == 1

        segunda = client.post(
            "/publish",
            json=evento,
        )

        assert segunda.status_code == 201
        assert segunda.json()["created"] is False
        assert segunda.json()["deliveries"] == 0

    with closing(open_db("broker")) as conn:
        total_eventos = conn.execute(
            "SELECT COUNT(*) FROM broker_events"
        ).fetchone()[0]

        total_entregas = conn.execute(
            "SELECT COUNT(*) FROM broker_deliveries"
        ).fetchone()[0]

        status_entrega = conn.execute(
            "SELECT status FROM broker_deliveries"
        ).fetchone()[0]

    assert total_eventos == 1
    assert total_entregas == 1
    assert status_entrega == "pending"
