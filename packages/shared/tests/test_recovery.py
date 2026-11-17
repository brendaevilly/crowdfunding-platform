"""Teste de recuperação de eventos pendentes da outbox."""

import sqlite3

import httpx

from shared.db import transaction
from shared.messaging_schema import install_messaging_schema
from shared.outbox import OutboxEvent, add
from shared.relay import publish_pending


def test_evento_pendente_e_publicado_apos_reinicio(
    tmp_path,
    monkeypatch,
):
    """Evento salvo antes da falha é publicado após retomada."""
    install_messaging_schema("campanhas", tmp_path)

    def salvar(conn: sqlite3.Connection) -> str:
        conn.execute(
            """
            CREATE TABLE campanhas_teste (
                id TEXT PRIMARY KEY
            )
            """
        )
        conn.execute(
            "INSERT INTO campanhas_teste (id) VALUES (?)",
            ("campanha-1",),
        )

        return add(
            conn,
            OutboxEvent(
                agregado_id="campanha-1",
                tipo_evento="CampanhaPublicada",
                payload={"campanhaId": "campanha-1"},
                correlation_id="correlation-1",
            ),
        )

    event_id = transaction(salvar, "campanhas", tmp_path)

    # Simula uma interrupção antes da publicação.
    # A transação já foi confirmada no banco.
    def consultar(conn: sqlite3.Connection):
        return conn.execute(
            """
            SELECT status
            FROM outbox_evento
            WHERE outbox_id = ?
            """,
            (event_id,),
        ).fetchone()[0]

    assert transaction(consultar, "campanhas", tmp_path) == "PENDENTE"

    eventos_recebidos = []

    def fake_post(url, json, timeout):
        eventos_recebidos.append(json)
        return httpx.Response(
            201,
            json={
                "eventId": json["eventId"],
                "created": True,
                "deliveries": 1,
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    # Simula o relay retomando após a interrupção.
    publicados = publish_pending(
        service="campanhas",
        broker_url="http://localhost:8001",
        data_dir=tmp_path,
    )

    assert publicados == 1
    assert len(eventos_recebidos) == 1
    assert eventos_recebidos[0]["eventId"] == event_id

    assert transaction(consultar, "campanhas", tmp_path) == "PUBLICADO"
