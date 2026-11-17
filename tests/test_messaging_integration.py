"""Testes de integração entre outbox, broker e consumidor."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from broker.app import app as broker_app
from broker.dispatcher import dispatch_pending
from shared.consumer import create_events_router
from shared.db import transaction
from shared.messaging_schema import install_messaging_schema
from shared.outbox import OutboxEvent, add
from shared.relay import publish_pending


@pytest.fixture
def ambiente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Path]]:
    """Inicializa o broker e os bancos isolados."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROKER_DISPATCH_ENABLED", "false")

    data_dir = tmp_path / "data"
    install_messaging_schema("campanhas", data_dir)
    install_messaging_schema("aportes", data_dir)

    with TestClient(broker_app) as broker_client:
        yield broker_client, data_dir


def salvar_evento(data_dir: Path) -> str:
    """Grava um evento na outbox de campanhas."""

    def salvar(conn: sqlite3.Connection) -> str:
        return add(
            conn,
            OutboxEvent(
                agregado_id="campanha-1",
                tipo_evento="CampanhaPublicada",
                payload={"campanhaId": "campanha-1"},
                correlation_id="correlation-1",
            ),
        )

    return transaction(salvar, "campanhas", data_dir)


def consultar_status(data_dir: Path, event_id: str) -> str:
    """Consulta o estado de um evento na outbox."""

    def consultar(conn: sqlite3.Connection) -> str:
        row = conn.execute(
            """
            SELECT status
            FROM outbox_evento
            WHERE outbox_id = ?
            """,
            (event_id,),
        ).fetchone()
        assert row is not None
        return str(row[0])

    return transaction(consultar, "campanhas", data_dir)


def test_publicacao_real_no_broker(
    ambiente: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """O relay publica no broker e confirma a outbox."""
    broker_client, data_dir = ambiente
    event_id = salvar_evento(data_dir)

    def post_local(url: str, json: dict[str, Any], timeout: float) -> httpx.Response:
        response = broker_client.post("/publish", json=json)
        return httpx.Response(
            response.status_code,
            json=response.json(),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", post_local)

    publicados = publish_pending(
        "campanhas",
        "http://broker",
        data_dir,
    )

    assert publicados == 1
    assert consultar_status(data_dir, event_id) == "PUBLICADO"

    def contar(conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT COUNT(*) FROM broker_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        assert row is not None
        return int(row[0])

    assert transaction(contar, "broker", data_dir) == 1


def test_broker_nao_duplica_evento(ambiente: tuple[TestClient, Path]) -> None:
    """O broker armazena um eventId somente uma vez."""
    broker_client, data_dir = ambiente

    evento = {
        "eventId": "evento-duplicado",
        "topic": "CampanhaPublicada",
        "payload": {"campanhaId": "campanha-1"},
        "correlationId": "correlation-1",
    }

    primeira = broker_client.post("/publish", json=evento)
    segunda = broker_client.post("/publish", json=evento)

    assert primeira.status_code == 201
    assert segunda.status_code == 201
    assert primeira.json()["created"] is True
    assert segunda.json()["created"] is False

    def contar(conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT COUNT(*) FROM broker_events WHERE event_id = ?",
            ("evento-duplicado",),
        ).fetchone()
        assert row is not None
        return int(row[0])

    assert transaction(contar, "broker", data_dir) == 1


def test_fluxo_completo_com_broker_real(
    ambiente: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outbox, relay, broker e consumidor funcionam juntos."""
    broker_client, data_dir = ambiente

    def preparar(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE efeitos_integracao (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campanha_id TEXT NOT NULL
            )
            """
        )

    transaction(preparar, "aportes", data_dir)

    def handler(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO efeitos_integracao (campanha_id) VALUES (?)",
            (payload["campanhaId"],),
        )

    consumer_app = FastAPI()
    consumer_app.include_router(
        create_events_router(
            service="aportes",
            handlers={"CampanhaPublicada": handler},
            data_dir=data_dir,
        )
    )

    with TestClient(consumer_app) as consumer_client:
        assinatura = broker_client.post(
            "/subscriptions",
            json={
                "service": "aportes",
                "topic": "CampanhaPublicada",
                "url": "http://consumer",
            },
        )
        assert assinatura.status_code == 201

        def post_local(url: str, json: dict[str, Any], timeout: float) -> httpx.Response:
            if url == "http://broker/publish":
                response = broker_client.post("/publish", json=json)
            elif url == "http://consumer/events":
                response = consumer_client.post("/events", json=json)
            else:
                raise AssertionError(f"URL inesperada: {url}")

            return httpx.Response(
                response.status_code,
                json=response.json(),
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx, "post", post_local)

        event_id = salvar_evento(data_dir)

        assert (
            publish_pending(
                "campanhas",
                "http://broker",
                data_dir,
            )
            == 1
        )

        assert consultar_status(data_dir, event_id) == "PUBLICADO"

        assert dispatch_pending() == 1
        assert dispatch_pending() == 0

        def contar_efeitos(conn: sqlite3.Connection) -> int:
            row = conn.execute("SELECT COUNT(*) FROM efeitos_integracao").fetchone()
            assert row is not None
            return int(row[0])

        assert transaction(contar_efeitos, "aportes", data_dir) == 1

        def consultar_entrega(conn: sqlite3.Connection) -> str:
            row = conn.execute(
                """
                SELECT d.status
                FROM broker_deliveries AS d
                JOIN broker_events AS e ON e.id = d.event_id
                WHERE e.event_id = ?
                """,
                (event_id,),
            ).fetchone()
            assert row is not None
            return str(row[0])

        assert transaction(consultar_entrega, "broker", data_dir) == "delivered"
