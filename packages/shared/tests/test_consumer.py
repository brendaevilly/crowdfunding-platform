"""Testes da rota de consumo idempotente de eventos."""

import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.consumer import create_events_router
from shared.db import transaction
from shared.messaging_schema import install_messaging_schema


def test_tres_entregas_produzem_um_efeito(tmp_path):
    """Três entregas do mesmo evento produzem apenas um efeito."""
    install_messaging_schema("aportes", tmp_path)

    def criar_tabela(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE efeitos_teste (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evento_id TEXT NOT NULL
            )
            """
        )

    transaction(criar_tabela, "aportes", tmp_path)

    def handler(
        conn: sqlite3.Connection,
        payload: dict,
    ) -> None:
        conn.execute(
            "INSERT INTO efeitos_teste (evento_id) VALUES (?)",
            (payload["aporteId"],),
        )

    app = FastAPI()
    app.include_router(
        create_events_router(
            service="aportes",
            handlers={"AporteConfirmado": handler},
            data_dir=tmp_path,
        )
    )

    evento = {
        "eventId": "evento-123",
        "topic": "AporteConfirmado",
        "correlationId": "correlation-123",
        "payload": {
            "eventId": "evento-123",
            "tipo": "AporteConfirmado",
            "versão": 1,
            "ocorridoEm": "2026-11-17T02:00:00+00:00",
            "correlationId": "correlation-123",
            "payload": {"aporteId": "aporte-1"},
        },
    }

    with TestClient(app) as client:
        respostas = [client.post("/events", json=evento) for _ in range(3)]

    assert all(resposta.status_code == 200 for resposta in respostas)

    assert [resposta.json()["processed"] for resposta in respostas] == [
        True,
        False,
        False,
    ]

    def contar(conn: sqlite3.Connection) -> int:
        return conn.execute("SELECT COUNT(*) FROM efeitos_teste").fetchone()[0]

    assert transaction(contar, "aportes", tmp_path) == 1
