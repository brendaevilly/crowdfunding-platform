"""Testes HTTP de integração dos eventos da Custódia."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import custodia_retornos.app as modulo_app
from contracts.topicos import APORTE_CONFIRMADO, CAMPANHA_PUBLICADA
from shared.consumer import create_events_router


def criar_entrega(
    event_id: str,
    topic: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Cria uma entrega no formato esperado pelo broker."""
    return {
        "eventId": event_id,
        "topic": topic,
        "payload": {
            "eventId": event_id,
            "tipo": topic,
            "versão": 1,
            "ocorridoEm": datetime.now(UTC).isoformat(),
            "correlationId": "teste-custodia",
            "payload": payload,
        },
    }


def campanha_payload() -> dict[str, Any]:
    return {
        "campanhaId": "campanha-1",
        "empreendedorId": "empreendedor-1",
        "meta": 100000,
        "prazoFim": "2026-12-31T23:59:59Z",
    }


def aporte_payload() -> dict[str, Any]:
    return {
        "aporteId": "aporte-1",
        "campanhaId": "campanha-1",
        "investidorId": "investidor-1",
        "valor": 5000,
        "confirmadoEm": datetime.now(UTC).isoformat(),
    }


def criar_cliente(
    monkeypatch: Any,
    tmp_path: Path,
) -> TestClient:
    """Cria aplicação com rota de eventos sem iniciar broker real."""

    def configurar_messaging(
        app: Any,
        *,
        service: str,
        handlers: dict[str, Any],
        data_dir: str | Path,
        **kwargs: Any,
    ) -> None:
        app.include_router(
            create_events_router(
                service=service,
                handlers=handlers,
                data_dir=data_dir,
            )
        )

    monkeypatch.setattr(
        modulo_app,
        "configure_messaging",
        configurar_messaging,
    )

    app = modulo_app.criar_custodia_app(tmp_path)
    return TestClient(app)


def test_aplicacao_inicializa_migrations(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    with criar_cliente(monkeypatch, tmp_path):
        from shared.db import open_db

        with open_db("custodia_retornos", tmp_path) as conn:
            tabelas = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }

    assert "custodia_contas" in tabelas
    assert "custodia_movimentacoes" in tabelas


def test_eventos_abrem_conta_e_registram_retencao(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    from shared.db import open_db

    with criar_cliente(monkeypatch, tmp_path) as client:
        campanha = client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-1",
                CAMPANHA_PUBLICADA,
                campanha_payload(),
            ),
        )

        aporte = client.post(
            "/events",
            json=criar_entrega(
                "evento-aporte-1",
                APORTE_CONFIRMADO,
                aporte_payload(),
            ),
        )

    assert campanha.status_code == 200
    assert campanha.json()["processed"] is True

    assert aporte.status_code == 200
    assert aporte.json()["processed"] is True

    with open_db("custodia_retornos", tmp_path) as conn:
        conta = conn.execute(
            "SELECT saldo_retido FROM custodia_contas WHERE campanha_id = ?",
            ("campanha-1",),
        ).fetchone()

        assert conta is not None
        assert conta[0] == 5000


def test_dez_entregas_do_mesmo_aporte_geram_uma_retencao(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    from shared.db import open_db

    with criar_cliente(monkeypatch, tmp_path) as client:
        client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-1",
                CAMPANHA_PUBLICADA,
                campanha_payload(),
            ),
        )

        respostas = [
            client.post(
                "/events",
                json=criar_entrega(
                    f"evento-aporte-{i}",
                    APORTE_CONFIRMADO,
                    aporte_payload(),
                ),
            )
            for i in range(10)
        ]

    assert all(resposta.status_code == 200 for resposta in respostas)

    with open_db("custodia_retornos", tmp_path) as conn:
        quantidade = conn.execute(
            """
            SELECT COUNT(*)
            FROM custodia_movimentacoes
            WHERE aporte_id = ? AND tipo = 'RETENCAO'
            """,
            ("aporte-1",),
        ).fetchone()

        saldo = conn.execute(
            "SELECT saldo_retido FROM custodia_contas WHERE campanha_id = ?",
            ("campanha-1",),
        ).fetchone()

    assert quantidade is not None
    assert quantidade[0] == 1
    assert saldo is not None
    assert saldo[0] == 5000


def test_aporte_antes_da_campanha_pode_ser_reprocessado(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    with criar_cliente(monkeypatch, tmp_path) as client:
        entrega = criar_entrega(
            "evento-aporte-antecipado",
            APORTE_CONFIRMADO,
            aporte_payload(),
        )

        primeira = client.post("/events", json=entrega)

        assert primeira.status_code == 500

        campanha = client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-1",
                CAMPANHA_PUBLICADA,
                campanha_payload(),
            ),
        )

        segunda = client.post("/events", json=entrega)

    assert campanha.status_code == 200
    assert segunda.status_code == 200
    assert segunda.json()["processed"] is True
