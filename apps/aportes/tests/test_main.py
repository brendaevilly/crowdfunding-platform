"""Testes da inicialização e do consumo de eventos de Aportes."""

import asyncio
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aportes.main import app
from aportes.repository import inicializar_banco
from shared.db import open_db


def preparar_ambiente(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Isola o banco e evita dependência de um broker real."""
    modulo = importlib.import_module("aportes.main")
    messaging = importlib.import_module("shared.messaging")
    consumer = importlib.import_module("shared.consumer")
    worker = importlib.import_module("aportes.reconciliacao_worker")

    monkeypatch.setattr(
        modulo,
        "inicializar_banco",
        lambda: inicializar_banco(tmp_path),
    )

    monkeypatch.setattr(
        messaging,
        "register_subscriptions",
        lambda **kwargs: None,
    )

    # O lifespan de messaging foi configurado na importação do app.
    # Redireciona a instalação do schema ao banco temporário.
    instalar_schema_original = messaging.install_messaging_schema

    def instalar_schema_teste(
        service: str,
        data_dir: str | Path = "data",
    ) -> None:
        if service == "aportes":
            instalar_schema_original(service, tmp_path)
        else:
            instalar_schema_original(service, data_dir)

    monkeypatch.setattr(
        messaging,
        "install_messaging_schema",
        instalar_schema_teste,
    )

    # O consumidor utiliza o data_dir definido na configuração
    # inicial. Redireciona suas transações ao banco temporário.
    transacao_original = consumer.transaction

    def transacao_teste(fn, service, data_dir="data"):
        if service == "aportes":
            return transacao_original(fn, service, tmp_path)
        return transacao_original(fn, service, data_dir)

    monkeypatch.setattr(
        consumer,
        "transaction",
        transacao_teste,
    )

    # Impede que o relay acesse o banco padrão durante os testes.
    # O broker não faz parte do comportamento testado aqui.
    def relay_teste(
        *,
        service,
        broker_url,
        data_dir="data",
        should_stop,
        **kwargs,
    ):
        return None

    monkeypatch.setattr(
        messaging,
        "run_relay",
        relay_teste,
    )

    # Mantém o worker isolado do banco padrão.
    async def reconciliacao_teste() -> None:
        try:
            await worker.executar_reconciliacao_periodica(
                data_dir=tmp_path,
            )
        except asyncio.CancelledError:
            raise

    monkeypatch.setattr(
        modulo,
        "executar_reconciliacao_periodica",
        reconciliacao_teste,
    )


def test_health_e_inicializacao_do_banco(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preparar_ambiente(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "aportes"

    conn = open_db("aportes", tmp_path)
    try:
        tabelas = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()

    assert {
        "aporte",
        "investidor_verificado",
        "outbox_evento",
        "evento_processado",
    }.issubset(tabelas)


def test_consumir_evento_identidade_verificada(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preparar_ambiente(monkeypatch, tmp_path)

    evento = {
        "eventId": "evento-kyc-1",
        "tipo": "identidade.verificada",
        "versão": 1,
        "ocorridoEm": "2026-11-18T12:00:00Z",
        "payload": {
            "usuarioId": "investidor-123",
            "verificadaEm": "2026-11-18T12:00:00Z",
        },
    }

    entrega = {
        "eventId": "evento-kyc-1",
        "topic": "identidade.verificada",
        "payload": evento,
    }

    with TestClient(app) as client:
        primeira = client.post("/events", json=entrega)
        segunda = client.post("/events", json=entrega)

    assert primeira.status_code == 200
    assert primeira.json()["processed"] is True

    assert segunda.status_code == 200
    assert segunda.json()["processed"] is False

    conn = open_db("aportes", tmp_path)
    try:
        quantidade = conn.execute(
            """
            SELECT COUNT(*)
            FROM investidor_verificado
            WHERE investidor_id = ?
            """,
            ("investidor-123",),
        ).fetchone()
    finally:
        conn.close()

    assert quantidade is not None
    assert quantidade[0] == 1


def test_eventos_diferentes_do_mesmo_usuario_nao_duplicam_registro(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Dois eventos distintos do mesmo usuário geram um único registro."""
    preparar_ambiente(monkeypatch, tmp_path)

    def entrega(event_id: str) -> dict[str, object]:
        return {
            "eventId": event_id,
            "topic": "identidade.verificada",
            "payload": {
                "eventId": event_id,
                "tipo": "identidade.verificada",
                "versão": 1,
                "ocorridoEm": "2026-11-18T12:00:00Z",
                "payload": {
                    "usuarioId": "investidor-123",
                    "verificadaEm": "2026-11-18T12:00:00Z",
                },
            },
        }

    with TestClient(app) as client:
        primeira = client.post("/events", json=entrega("evento-kyc-1"))
        segunda = client.post("/events", json=entrega("evento-kyc-2"))

    assert primeira.status_code == 200
    assert primeira.json()["processed"] is True

    assert segunda.status_code == 200
    assert segunda.json()["processed"] is True

    conn = open_db("aportes", tmp_path)
    try:
        quantidade = conn.execute(
            """
            SELECT COUNT(*)
            FROM investidor_verificado
            WHERE investidor_id = ?
            """,
            ("investidor-123",),
        ).fetchone()
    finally:
        conn.close()

    assert quantidade is not None
    assert quantidade[0] == 1
