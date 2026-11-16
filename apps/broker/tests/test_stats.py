
"""Testes das estatísticas de entregas do broker."""

from contextlib import closing

from fastapi.testclient import TestClient

from broker.app import app
from shared.db import open_db


def test_stats_contabiliza_status_por_topico(
    tmp_path, monkeypatch
):
    """Conta entregas pendentes, entregues e na DLQ."""
    monkeypatch.chdir(tmp_path)
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

        # Cria quatro eventos e quatro entregas.
        for numero in range(1, 5):
            evento = {
                "eventId": f"evento-stats-{numero}",
                "topic": "AporteConfirmado",
                "payload": {"numero": numero},
                "correlationId": "correlation-stats",
            }

            resposta = client.post(
                "/publish",
                json=evento,
            )
            assert resposta.status_code == 201

        # Simula os diferentes estados das entregas.
        with closing(open_db("broker")) as conn:
            conn.execute(
                """
                UPDATE broker_deliveries
                SET status = 'processing',
                    lease_token = 'token-teste'
                WHERE id = 2
                """
            )

            conn.execute(
                """
                UPDATE broker_deliveries
                SET status = 'delivered',
                    attempts = 1,
                    delivered_at = CURRENT_TIMESTAMP
                WHERE id = 3
                """
            )

            conn.execute(
                """
                UPDATE broker_deliveries
                SET status = 'dlq',
                    attempts = 5,
                    last_error = 'Falha simulada'
                WHERE id = 4
                """
            )

            conn.commit()

        resposta = client.get("/stats")

        assert resposta.status_code == 200

        estatisticas = resposta.json()["topics"]

        assert "AporteConfirmado" in estatisticas

        dados = estatisticas["AporteConfirmado"]

        # pending + processing = 2 pendentes.
        assert dados["pending"] == 2
        assert dados["delivered"] == 1
        assert dados["dlq"] == 1

        assert sum(dados.values()) == 4
