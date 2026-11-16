"""Testes do cadastro de assinaturas do broker."""

from fastapi.testclient import TestClient

from broker.app import app
from shared.db import open_db


def test_subscription_idempotente(tmp_path, monkeypatch):
    """Uma assinatura repetida não deve criar outro registro."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROKER_DISPATCH_ENABLED", "false")

    assinatura = {
        "service": "notificacao",
        "topic": "AporteConfirmado",
        "url": "http://localhost:3005",
    }

    with TestClient(app) as client:
        primeira = client.post(
            "/subscriptions",
            json=assinatura,
        )

        segunda = client.post(
            "/subscriptions",
            json=assinatura,
        )

    assert primeira.status_code == 201
    assert primeira.json()["created"] is True

    assert segunda.status_code == 201
    assert segunda.json()["created"] is False

    conn = open_db("broker")

    try:
        quantidade = conn.execute(
            """
            SELECT COUNT(*)
            FROM broker_subscriptions
            """
        ).fetchone()[0]
    finally:
        conn.close()

    assert quantidade == 1
