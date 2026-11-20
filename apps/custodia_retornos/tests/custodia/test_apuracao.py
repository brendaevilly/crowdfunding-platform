"""Testes da apuração de campanhas e relógio injetável."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from custodia_retornos.app import criar_custodia_app
from custodia_retornos.custodia.apuracao import apurar_pendentes
from custodia_retornos.custodia.clock import AdjustableClock
from shared.db import migrate, transaction
from shared.messaging_schema import install_messaging_schema

MIGRATIONS = Path("apps/custodia_retornos/migrations")


@pytest.fixture
def ambiente(tmp_path: Path) -> Path:
    migrate("custodia_retornos", MIGRATIONS, tmp_path)
    install_messaging_schema("custodia_retornos", tmp_path)
    return tmp_path


def preparar_campanha(
    data_dir: Path,
    *,
    campanha_id: str,
    meta: int,
    saldo: int,
    prazo: datetime,
) -> None:
    def operacao(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO custodia_contas (
                campanha_id, meta, prazo_fim,
                saldo_retido, empreendedor_id
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                campanha_id,
                meta,
                prazo.isoformat(),
                saldo,
                "empreendedor-1",
            ),
        )
        conn.execute(
            """
            INSERT INTO custodia_investidores (
                campanha_id, investidor_id
            )
            VALUES (?, ?)
            """,
            (campanha_id, "investidor-1"),
        )

    transaction(operacao, "custodia_retornos", data_dir)


@pytest.mark.parametrize(
    ("saldo", "meta", "esperado"),
    [
        (1000, 1000, "SUCESSO"),
        (1500, 1000, "SUCESSO"),
        (999, 1000, "FALHA"),
        (0, 1000, "FALHA"),
    ],
)
def test_resultado_e_idempotencia(
    ambiente: Path,
    saldo: int,
    meta: int,
    esperado: str,
) -> None:
    agora = datetime(2026, 11, 20, tzinfo=UTC)
    clock = AdjustableClock(agora)
    preparar_campanha(
        ambiente,
        campanha_id="campanha-1",
        meta=meta,
        saldo=saldo,
        prazo=agora - timedelta(seconds=1),
    )

    assert apurar_pendentes(clock, ambiente) == 1
    assert apurar_pendentes(clock, ambiente) == 0

    def verificar(conn: sqlite3.Connection) -> tuple[list[tuple[str]], list[tuple[str, str]]]:
        resultados = conn.execute("SELECT resultado FROM custodia_resultados").fetchall()
        eventos = conn.execute(
            """
            SELECT tipo_evento, payload
            FROM outbox_evento
            """
        ).fetchall()
        return resultados, eventos

    resultados, eventos = transaction(verificar, "custodia_retornos", ambiente)

    assert resultados == [(esperado,)]
    assert len(eventos) == 1
    assert eventos[0][0] == "campanha.resultado"
    assert '"investidorIds": ["investidor-1"]' in eventos[0][1]


def test_prazo_futuro_nao_apura(ambiente: Path) -> None:
    agora = datetime(2026, 11, 20, tzinfo=UTC)
    clock = AdjustableClock(agora)

    preparar_campanha(
        ambiente,
        campanha_id="campanha-futura",
        meta=1000,
        saldo=1000,
        prazo=agora + timedelta(days=1),
    )

    assert apurar_pendentes(clock, ambiente) == 0

    clock.advance(86400)

    assert apurar_pendentes(clock, ambiente) == 1
    assert apurar_pendentes(clock, ambiente) == 0


def test_endpoint_advance_apura_imediatamente(
    ambiente: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTODIA_RETORNOS_MESSAGING_ENABLED", "false")

    agora = datetime(2026, 11, 20, tzinfo=UTC)
    clock = AdjustableClock(agora)

    preparar_campanha(
        ambiente,
        campanha_id="campanha-endpoint",
        meta=1000,
        saldo=1200,
        prazo=agora + timedelta(hours=1),
    )

    app = criar_custodia_app(
        data_dir=ambiente,
        clock=clock,
        dev_mode=True,
        scheduler_enabled=False,
    )

    with TestClient(app) as client:
        resposta = client.post(
            "/_dev/clock/advance",
            json={"seconds": 3600},
        )

        assert resposta.status_code == 200
        assert resposta.json()["apuradas"] == 1

        segunda = client.post(
            "/_dev/clock/advance",
            json={"seconds": 1},
        )

        assert segunda.status_code == 200
        assert segunda.json()["apuradas"] == 0


def test_endpoint_indisponivel_fora_dev(
    ambiente: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTODIA_RETORNOS_MESSAGING_ENABLED", "false")

    app = criar_custodia_app(
        data_dir=ambiente,
        dev_mode=False,
        scheduler_enabled=False,
    )

    with TestClient(app) as client:
        resposta = client.post(
            "/_dev/clock/advance",
            json={"seconds": 3600},
        )

    assert resposta.status_code == 404


def test_clock_nao_permite_voltar_no_tempo() -> None:
    clock = AdjustableClock(datetime(2026, 11, 20, tzinfo=UTC))

    with pytest.raises(ValueError):
        clock.advance(-1)
