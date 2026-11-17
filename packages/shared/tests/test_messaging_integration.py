
"""Testes de integração do shared messaging com o broker real."""

import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from broker.app import app as broker_app
from broker.dispatcher import dispatch_pending
from shared.db import transaction
from shared.messaging_schema import install_messaging_schema
from shared.outbox import OutboxEvent, add
from shared.relay import publish_pending


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """Prepara bancos isolados para broker e serviço."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROKER_DISPATCH_ENABLED", "false")

    install_messaging_schema("campanhas", tmp_path)

    with TestClient(broker_app) as client:
        yield client, tmp_path


def test_publicacao_real_no_broker(ambiente, monkeypatch):
    """Relay publica evento usando a rota real do broker."""
    client, data_dir = ambiente

    def salvar(conn: sqlite3.Connection):
        return add(
            conn,
            OutboxEvent(
                agregado_id="campanha-1",
                tipo_evento="CampanhaPublicada",
                payload={"campanhaId": "campanha-1"},
                correlation_id="correlation-1",
            ),
        )

    event_id = transaction(salvar, "campanhas", data_dir)

    original_post = httpx.post

    def post_local(url, json, timeout):
        if url.endswith("/publish"):
            response = client.post("/publish", json=json)
            return httpx.Response(
                response.status_code,
                json=response.json(),
                request=httpx.Request("POST", url),
            )

        return original_post(url, json=json, timeout=timeout)

    monkeypatch.setattr(httpx, "post", post_local)

    publicados = publish_pending(
        "campanhas",
        "http://broker",
        data_dir,
    )

    assert publicados == 1

    def consultar(conn: sqlite3.Connection):
        return conn.execute(
            """
            SELECT status
            FROM outbox_evento
            WHERE outbox_id = ?
            """,
            (event_id,),
        ).fetchone()[0]

    assert transaction(consultar, "campanhas", data_dir) == "PUBLICADO"

    def consultar_broker(conn: sqlite3.Connection):
        return conn.execute(
            """
            SELECT COUNT(*)
            FROM broker_events
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()[0]

    assert transaction(consultar_broker, "broker", data_dir) == 1


def test_broker_nao_duplica_evento(ambiente):
    """Mesmo eventId publicado duas vezes gera um registro."""
    client, data_dir = ambiente

    evento = {
        "eventId": "evento-duplicado",
        "topic": "CampanhaPublicada",
        "payload": {"campanhaId": "campanha-1"},
        "correlationId": "correlation-1",
    }

    primeira = client.post("/publish", json=evento)
    segunda = client.post("/publish", json=evento)

    assert primeira.status_code == 201
    assert segunda.status_code == 201
    assert primeira.json()["created"] is True
    assert segunda.json()["created"] is False

    def contar(conn: sqlite3.Connection):
        return conn.execute(
            """
            SELECT COUNT(*)
            FROM broker_events
            WHERE event_id = ?
            """,
            ("evento-duplicado",),
        ).fetchone()[0]

    assert transaction(contar, "broker", data_dir) == 1
