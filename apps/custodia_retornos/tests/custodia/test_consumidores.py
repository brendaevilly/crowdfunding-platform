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

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


@pytest.fixture
def banco(tmp_path: Path) -> Path:
    migrate("custodia_retornos", MIGRATIONS, tmp_path)
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
