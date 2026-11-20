"""Testes dos consumidores de eventos da custódia."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts.eventos import AporteConfirmado, CampanhaPublicada
from custodia_retornos.custodia.consumidores import (
    ContaCustodiaNaoEncontradaErro,
    consumir_aporte_confirmado,
    consumir_campanha_publicada,
)
from custodia_retornos.custodia.repositorio import (
    buscar_conta,
    listar_movimentacoes,
)
from shared.db import migrate, transaction
from shared.messaging_schema import install_messaging_schema

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


@pytest.fixture
def banco(tmp_path: Path) -> Path:
    migrate("custodia_retornos", MIGRATIONS, tmp_path)
    install_messaging_schema("custodia_retornos", tmp_path)
    return tmp_path


def campanha_payload() -> dict[str, object]:
    evento = CampanhaPublicada(
        campanha_id="campanha-1",
        empreendedor_id="empreendedor-1",
        meta=100000,
        prazo_fim=datetime(2026, 12, 31, tzinfo=UTC),
    )
    return evento.model_dump(mode="json", by_alias=True)


def aporte_payload() -> dict[str, object]:
    evento = AporteConfirmado(
        aporte_id="aporte-1",
        campanha_id="campanha-1",
        investidor_id="investidor-1",
        valor=5000,
        confirmado_em=datetime(2026, 11, 20, tzinfo=UTC),
    )
    return evento.model_dump(mode="json", by_alias=True)


def test_campanha_publicada_abre_conta(banco: Path) -> None:
    transaction(
        lambda conn: consumir_campanha_publicada(conn, campanha_payload()),
        "custodia_retornos",
        banco,
    )

    conta = transaction(
        lambda conn: buscar_conta(conn, "campanha-1"),
        "custodia_retornos",
        banco,
    )

    assert conta is not None
    assert conta.meta == 100000
    assert conta.saldo_retido == 0


def test_campanha_publicada_e_idempotente(banco: Path) -> None:
    def operacao(conn: sqlite3.Connection) -> None:
        consumir_campanha_publicada(conn, campanha_payload())
        consumir_campanha_publicada(conn, campanha_payload())

    transaction(operacao, "custodia_retornos", banco)

    conta = transaction(
        lambda conn: buscar_conta(conn, "campanha-1"),
        "custodia_retornos",
        banco,
    )

    assert conta is not None
    assert conta.meta == 100000


def test_aporte_antes_da_campanha_gera_erro(banco: Path) -> None:
    with pytest.raises(ContaCustodiaNaoEncontradaErro):
        transaction(
            lambda conn: consumir_aporte_confirmado(conn, aporte_payload()),
            "custodia_retornos",
            banco,
        )

    movimentacoes = transaction(
        lambda conn: listar_movimentacoes(conn, "campanha-1"),
        "custodia_retornos",
        banco,
    )

    assert movimentacoes == ()


def test_aporte_confirmado_registra_retencao(banco: Path) -> None:
    def operacao(conn: sqlite3.Connection) -> None:
        consumir_campanha_publicada(conn, campanha_payload())
        consumir_aporte_confirmado(conn, aporte_payload())

    transaction(operacao, "custodia_retornos", banco)

    def consultar(conn: sqlite3.Connection) -> tuple[int, int]:
        conta = buscar_conta(conn, "campanha-1")
        assert conta is not None
        movimentacoes = listar_movimentacoes(
            conn,
            "campanha-1",
        )
        return conta.saldo_retido, len(movimentacoes)

    saldo, quantidade = transaction(
        consultar,
        "custodia_retornos",
        banco,
    )

    assert saldo == 5000
    assert quantidade == 1


def test_dez_entregas_do_aporte_geram_uma_retencao(banco: Path) -> None:
    def operacao(conn: sqlite3.Connection) -> None:
        consumir_campanha_publicada(conn, campanha_payload())

        for _ in range(10):
            consumir_aporte_confirmado(conn, aporte_payload())

    transaction(operacao, "custodia_retornos", banco)

    def consultar(conn: sqlite3.Connection) -> tuple[int, int]:
        conta = buscar_conta(conn, "campanha-1")
        assert conta is not None
        movimentacoes = listar_movimentacoes(
            conn,
            "campanha-1",
        )
        return conta.saldo_retido, len(movimentacoes)

    saldo, quantidade = transaction(
        consultar,
        "custodia_retornos",
        banco,
    )

    assert saldo == 5000
    assert quantidade == 1


def test_resultado_sucesso_dispara_liquidacao(
    banco: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contracts.eventos import ResultadoCampanha, ResultadoFinal
    from custodia_retornos.custodia.consumidores import (
        consumir_resultado_campanha,
    )

    monkeypatch.setenv("CUSTODIA_TAXA_PERCENTUAL", "10")

    encerrada = datetime(2026, 11, 20, tzinfo=UTC)

    def operacao(conn: sqlite3.Connection) -> None:
        consumir_campanha_publicada(conn, campanha_payload())

        for aporte_id, investidor_id, valor in (
            ("aporte-1", "investidor-1", 60000),
            ("aporte-2", "investidor-2", 40000),
        ):
            evento = AporteConfirmado(
                aporte_id=aporte_id,
                campanha_id="campanha-1",
                investidor_id=investidor_id,
                valor=valor,
                confirmado_em=encerrada,
            )
            consumir_aporte_confirmado(
                conn,
                evento.model_dump(mode="json", by_alias=True),
            )

        resultado = ResultadoCampanha(
            campanha_id="campanha-1",
            empreendedor_id="empreendedor-1",
            resultado=ResultadoFinal.SUCESSO,
            valor_arrecadado=100000,
            investidor_ids=("investidor-1", "investidor-2"),
            encerrada_em=encerrada,
        )

        # Simula o resultado persistido pela apuração da Issue #26.
        conn.execute(
            """
            INSERT INTO custodia_resultados (
                campanha_id, resultado, valor_arrecadado, encerrada_em
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                "campanha-1",
                "SUCESSO",
                100000,
                encerrada.isoformat(),
            ),
        )

        payload = resultado.model_dump(mode="json", by_alias=True)
        consumir_resultado_campanha(conn, payload)

    transaction(operacao, "custodia_retornos", banco)

    def consultar(conn: sqlite3.Connection) -> tuple[int, int, int]:
        conta = buscar_conta(conn, "campanha-1")
        assert conta is not None

        valores = conn.execute(
            """
            SELECT tipo, valor
            FROM custodia_movimentacoes
            WHERE campanha_id = ?
            """,
            ("campanha-1",),
        ).fetchall()

        liberacao = sum(int(valor) for tipo, valor in valores if tipo == "LIBERACAO")
        taxa = sum(int(valor) for tipo, valor in valores if tipo == "TAXA")

        return conta.saldo_retido, liberacao, taxa

    saldo, liberacao, taxa = transaction(consultar, "custodia_retornos", banco)

    assert saldo == 0
    assert liberacao == 90000
    assert taxa == 10000


def test_resultado_falha_dispara_devolucao_integral(
    banco: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contracts.eventos import ResultadoCampanha, ResultadoFinal
    from custodia_retornos.custodia.consumidores import (
        consumir_resultado_campanha,
    )

    monkeypatch.setenv("CUSTODIA_TAXA_PERCENTUAL", "10")

    encerrada = datetime(2026, 11, 20, tzinfo=UTC)

    def operacao(conn: sqlite3.Connection) -> None:
        consumir_campanha_publicada(conn, campanha_payload())

        aportes = (
            ("aporte-1", "investidor-1", 60000),
            ("aporte-2", "investidor-2", 30000),
        )

        for aporte_id, investidor_id, valor in aportes:
            evento = AporteConfirmado(
                aporte_id=aporte_id,
                campanha_id="campanha-1",
                investidor_id=investidor_id,
                valor=valor,
                confirmado_em=encerrada,
            )
            consumir_aporte_confirmado(
                conn,
                evento.model_dump(mode="json", by_alias=True),
            )

        conn.execute(
            """
            INSERT INTO custodia_resultados (
                campanha_id, resultado, valor_arrecadado, encerrada_em
            )
            VALUES (?, ?, ?, ?)
            """,
            ("campanha-1", "FALHA", 90000, encerrada.isoformat()),
        )

        resultado = ResultadoCampanha(
            campanha_id="campanha-1",
            empreendedor_id="empreendedor-1",
            resultado=ResultadoFinal.FALHA,
            valor_arrecadado=90000,
            investidor_ids=("investidor-1", "investidor-2"),
            encerrada_em=encerrada,
        )

        consumir_resultado_campanha(
            conn,
            resultado.model_dump(mode="json", by_alias=True),
        )

    transaction(operacao, "custodia_retornos", banco)

    def consultar(
        conn: sqlite3.Connection,
    ) -> tuple[
        int,
        dict[str, int],
        int,
    ]:
        conta = buscar_conta(conn, "campanha-1")
        assert conta is not None

        movimentacoes = conn.execute(
            """
            SELECT tipo, aporte_id, valor
            FROM custodia_movimentacoes
            WHERE campanha_id = ?
            """,
            ("campanha-1",),
        ).fetchall()

        devolucoes = {
            str(aporte_id): int(valor)
            for tipo, aporte_id, valor in movimentacoes
            if tipo == "DEVOLUCAO"
        }

        eventos = conn.execute(
            """
            SELECT COUNT(*)
            FROM outbox_evento
            WHERE tipo_evento = 'campanha.liquidada'
            """
        ).fetchone()[0]

        return conta.saldo_retido, devolucoes, int(eventos)

    saldo, devolucoes, eventos = transaction(consultar, "custodia_retornos", banco)

    assert saldo == 0
    assert devolucoes == {
        "aporte-1": 60000,
        "aporte-2": 30000,
    }
    assert eventos == 0


def test_resultado_duplicado_nao_duplica_liquidacao(
    banco: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contracts.eventos import ResultadoCampanha, ResultadoFinal
    from custodia_retornos.custodia.consumidores import (
        consumir_resultado_campanha,
    )

    monkeypatch.setenv("CUSTODIA_TAXA_PERCENTUAL", "10")

    encerrada = datetime(2026, 11, 20, tzinfo=UTC)

    def operacao(conn: sqlite3.Connection) -> None:
        consumir_campanha_publicada(conn, campanha_payload())

        for aporte_id, investidor_id, valor in (
            ("aporte-1", "investidor-1", 60000),
            ("aporte-2", "investidor-2", 40000),
        ):
            evento = AporteConfirmado(
                aporte_id=aporte_id,
                campanha_id="campanha-1",
                investidor_id=investidor_id,
                valor=valor,
                confirmado_em=encerrada,
            )
            consumir_aporte_confirmado(
                conn,
                evento.model_dump(mode="json", by_alias=True),
            )

        conn.execute(
            """
            INSERT INTO custodia_resultados (
                campanha_id, resultado, valor_arrecadado, encerrada_em
            )
            VALUES (?, ?, ?, ?)
            """,
            ("campanha-1", "SUCESSO", 100000, encerrada.isoformat()),
        )

        resultado = ResultadoCampanha(
            campanha_id="campanha-1",
            empreendedor_id="empreendedor-1",
            resultado=ResultadoFinal.SUCESSO,
            valor_arrecadado=100000,
            investidor_ids=("investidor-1", "investidor-2"),
            encerrada_em=encerrada,
        )

        payload = resultado.model_dump(mode="json", by_alias=True)

        consumir_resultado_campanha(conn, payload)
        consumir_resultado_campanha(conn, payload)

    transaction(operacao, "custodia_retornos", banco)

    def consultar(conn: sqlite3.Connection) -> tuple[int, int, int, int]:
        conta = buscar_conta(conn, "campanha-1")
        assert conta is not None

        liberacoes = conn.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(valor), 0)
            FROM custodia_movimentacoes
            WHERE campanha_id = ? AND tipo = 'LIBERACAO'
            """,
            ("campanha-1",),
        ).fetchone()

        taxas = conn.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(valor), 0)
            FROM custodia_movimentacoes
            WHERE campanha_id = ? AND tipo = 'TAXA'
            """,
            ("campanha-1",),
        ).fetchone()

        eventos = conn.execute(
            """
            SELECT COUNT(*)
            FROM outbox_evento
            WHERE tipo_evento = 'campanha.liquidada'
            """
        ).fetchone()[0]

        return (
            conta.saldo_retido,
            int(liberacoes[1]),
            int(taxas[1]),
            int(eventos),
        )

    saldo, liberacao, taxa, eventos = transaction(consultar, "custodia_retornos", banco)

    assert saldo == 0
    assert liberacao == 90000
    assert taxa == 10000
    assert eventos == 1
