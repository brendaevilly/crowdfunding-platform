"""Testes da rota de consumo idempotente de eventos."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts.eventos import AporteConfirmado
from contracts.topicos import APORTE_CONFIRMADO
from shared.consumer import create_events_router
from shared.db import transaction
from shared.messaging_schema import install_messaging_schema


def criar_app(tmp_path: Path, handler: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_events_router(
            service="aportes",
            handlers={APORTE_CONFIRMADO: handler},
            data_dir=tmp_path,
        )
    )
    return app


def criar_evento(
    *,
    payload: dict[str, Any] | None = None,
    versao: int = 1,
) -> dict[str, Any]:
    event_id = "evento-123"
    correlation_id = "correlation-123"

    if payload is None:
        contrato = AporteConfirmado(
            aporte_id="aporte-1",
            campanha_id="campanha-1",
            investidor_id="usuario-2",
            valor=1000,
            confirmado_em=datetime.now(UTC),
        )
        payload = contrato.model_dump(by_alias=True, mode="json")

    return {
        "eventId": event_id,
        "topic": APORTE_CONFIRMADO,
        "correlationId": correlation_id,
        "payload": {
            "eventId": event_id,
            "tipo": APORTE_CONFIRMADO,
            "versão": versao,
            "ocorridoEm": datetime.now(UTC).isoformat(),
            "correlationId": correlation_id,
            "payload": payload,
        },
    }


def test_tres_entregas_produzem_um_efeito(tmp_path: Path) -> None:
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
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            "INSERT INTO efeitos_teste (evento_id) VALUES (?)",
            (payload["aporteId"],),
        )

    app = criar_app(tmp_path, handler)
    evento = criar_evento()

    with TestClient(app) as client:
        respostas = [client.post("/events", json=evento) for _ in range(3)]

    assert all(resposta.status_code == 200 for resposta in respostas)
    assert [r.json()["processed"] for r in respostas] == [
        True,
        False,
        False,
    ]

    def contar(conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COUNT(*) FROM efeitos_teste").fetchone()
        assert row is not None
        return int(row[0])

    assert transaction(contar, "aportes", tmp_path) == 1


def test_consumidor_rejeita_payload_invalido(tmp_path: Path) -> None:
    """Payload incompatível com o contrato deve retornar HTTP 422."""
    install_messaging_schema("aportes", tmp_path)

    app = criar_app(tmp_path, lambda conn, payload: None)
    evento = criar_evento(payload={})

    with TestClient(app) as client:
        resposta = client.post("/events", json=evento)

    assert resposta.status_code == 422
    assert "Contrato de evento inválido" in resposta.json()["detail"]


def test_consumidor_rejeita_versao_nao_suportada(
    tmp_path: Path,
) -> None:
    """Versão de schema desconhecida deve retornar HTTP 422."""
    install_messaging_schema("aportes", tmp_path)

    app = criar_app(tmp_path, lambda conn, payload: None)
    evento = criar_evento(versao=999)

    with TestClient(app) as client:
        resposta = client.post("/events", json=evento)

    assert resposta.status_code == 422
    assert "schemaVersion" in resposta.json()["detail"]


def test_consumidor_rejeita_tipo_diferente_do_topico(
    tmp_path: Path,
) -> None:
    """Tipo do envelope deve corresponder ao tópico da entrega."""
    install_messaging_schema("aportes", tmp_path)

    app = criar_app(tmp_path, lambda conn, payload: None)
    evento = criar_evento()
    evento["payload"]["tipo"] = "topico.incorreto"

    with TestClient(app) as client:
        resposta = client.post("/events", json=evento)

    assert resposta.status_code == 422
    assert "não corresponde ao tópico" in resposta.json()["detail"]
