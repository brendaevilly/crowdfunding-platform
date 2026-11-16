
"""Testes do cadastro de assinaturas do broker."""

from fastapi.testclient import TestClient

from broker.app import app


def test_subscription_idempotente(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    client = TestClient(app)

    assinatura = {
        "service": "notificacao",
        "topic": "AporteConfirmado",
        "url": "http://localhost:3005",
    }

    primeira = client.post("/subscriptions", json=assinatura)
    segunda = client.post("/subscriptions", json=assinatura)

    assert primeira.status_code == 201
    assert primeira.json()["created"] is True

    assert segunda.status_code == 201
    assert segunda.json()["created"] is False
