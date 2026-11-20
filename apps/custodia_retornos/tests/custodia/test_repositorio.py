"""Testes de persistência da custódia."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from custodia_retornos.custodia.dominio import (
    ContaCustodia,
    Movimentacao,
)
from custodia_retornos.custodia.repositorio import (
    abrir_conta,
    buscar_conta,
    listar_movimentacoes,
    registrar_movimentacao,
)
from shared.db import migrate, transaction

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


@pytest.fixture
def banco(tmp_path: Path) -> Path:
    migrate("custodia_retornos", MIGRATIONS, tmp_path)
    return tmp_path


def test_abrir_conta_idempotente(banco: Path) -> None:
    conta = ContaCustodia.abrir("campanha-1", 100000, datetime(2026, 12, 31, tzinfo=UTC))

    primeira = transaction(
        lambda conn: abrir_conta(conn, conta),
        "custodia_retornos",
        banco,
    )
    segunda = transaction(
        lambda conn: abrir_conta(conn, conta),
        "custodia_retornos",
        banco,
    )

    assert primeira is True
    assert segunda is False


def test_registrar_retencao_atualiza_saldo(banco: Path) -> None:
    conta = ContaCustodia.abrir("campanha-1", 100000, datetime(2026, 12, 31, tzinfo=UTC))
    movimentacao = Movimentacao.criar_retencao("campanha-1", "aporte-1", 5000)

    def operacao(conn: sqlite3.Connection) -> bool:
        abrir_conta(conn, conta)
        return registrar_movimentacao(conn, movimentacao)

    assert transaction(operacao, "custodia_retornos", banco) is True

    conta_salva = transaction(
        lambda conn: buscar_conta(conn, "campanha-1"),
        "custodia_retornos",
        banco,
    )

    assert conta_salva is not None
    assert conta_salva.saldo_retido == 5000


def test_dez_retencoes_iguais_geram_apenas_uma(banco: Path) -> None:
    conta = ContaCustodia.abrir("campanha-1", 100000, datetime(2026, 12, 31, tzinfo=UTC))
    movimentacao = Movimentacao.criar_retencao("campanha-1", "aporte-1", 5000)

    def operacao(conn: sqlite3.Connection) -> list[bool]:
        abrir_conta(conn, conta)
        return [registrar_movimentacao(conn, movimentacao) for _ in range(10)]

    resultados = transaction(operacao, "custodia_retornos", banco)

    assert resultados.count(True) == 1
    assert resultados.count(False) == 9

    saldo = transaction(
        lambda conn: buscar_conta(conn, "campanha-1"),
        "custodia_retornos",
        banco,
    )
    assert saldo is not None
    assert saldo.saldo_retido == 5000


def test_saldo_igual_a_soma_das_movimentacoes(banco: Path) -> None:
    conta = ContaCustodia.abrir("campanha-1", 100000, datetime(2026, 12, 31, tzinfo=UTC))

    primeira = Movimentacao.criar_retencao("campanha-1", "a1", 5000)
    segunda = Movimentacao.criar_retencao("campanha-1", "a2", 3000)

    def operacao(conn: sqlite3.Connection) -> None:
        abrir_conta(conn, conta)
        registrar_movimentacao(conn, primeira)
        registrar_movimentacao(conn, segunda)

    transaction(operacao, "custodia_retornos", banco)

    def verificar(conn: sqlite3.Connection) -> tuple[int, int]:
        conta_salva = buscar_conta(conn, "campanha-1")
        assert conta_salva is not None
        movimentacoes = listar_movimentacoes(conn, "campanha-1")
        soma = sum(m.valor for m in movimentacoes)
        return conta_salva.saldo_retido, soma

    saldo, soma = transaction(verificar, "custodia_retornos", banco)

    assert saldo == soma == 8000


def test_movimentacao_nao_pode_ser_alterada(banco: Path) -> None:
    conta = ContaCustodia.abrir("campanha-1", 100000, datetime(2026, 12, 31, tzinfo=UTC))
    movimentacao = Movimentacao.criar_retencao("campanha-1", "aporte-1", 5000)

    def operacao(conn: sqlite3.Connection) -> None:
        abrir_conta(conn, conta)
        registrar_movimentacao(conn, movimentacao)

    transaction(operacao, "custodia_retornos", banco)

    with pytest.raises(sqlite3.IntegrityError):
        transaction(
            lambda conn: conn.execute(
                """
                UPDATE custodia_movimentacoes
                SET valor = 999
                """
            ),
            "custodia_retornos",
            banco,
        )


def test_movimentacao_nao_pode_ser_excluida(banco: Path) -> None:
    conta = ContaCustodia.abrir("campanha-1", 100000, datetime(2026, 12, 31, tzinfo=UTC))
    movimentacao = Movimentacao.criar_retencao("campanha-1", "aporte-1", 5000)

    def operacao(conn: sqlite3.Connection) -> None:
        abrir_conta(conn, conta)
        registrar_movimentacao(conn, movimentacao)

    transaction(operacao, "custodia_retornos", banco)

    with pytest.raises(sqlite3.IntegrityError):
        transaction(
            lambda conn: conn.execute("DELETE FROM custodia_movimentacoes"),
            "custodia_retornos",
            banco,
        )


@settings(max_examples=50, deadline=None)
@given(
    valores=st.lists(
        st.integers(min_value=1, max_value=100000),
        min_size=1,
        max_size=20,
    )
)
def test_propriedade_saldo_igual_a_soma_das_movimentacoes(
    valores: list[int],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """O saldo persistido deve sempre corresponder à soma das retenções."""

    banco = tmp_path_factory.mktemp("custodia_propriedade")
    migrate("custodia_retornos", MIGRATIONS, banco)

    conta = ContaCustodia.abrir(
        "campanha-propriedade",
        sum(valores) + 1,
        datetime(2026, 12, 31, tzinfo=UTC),
    )

    movimentacoes = [
        Movimentacao.criar_retencao(
            "campanha-propriedade",
            f"aporte-{indice}",
            valor,
        )
        for indice, valor in enumerate(valores)
    ]

    def registrar(conn: sqlite3.Connection) -> None:
        abrir_conta(conn, conta)

        for movimentacao in movimentacoes:
            registrar_movimentacao(conn, movimentacao)

    transaction(registrar, "custodia_retornos", banco)

    def verificar(conn: sqlite3.Connection) -> tuple[int, int]:
        conta_salva = buscar_conta(conn, "campanha-propriedade")
        assert conta_salva is not None

        registros = listar_movimentacoes(conn, "campanha-propriedade")

        return (
            conta_salva.saldo_retido,
            sum(m.valor for m in registros),
        )

    saldo, soma = transaction(
        verificar,
        "custodia_retornos",
        banco,
    )

    assert saldo == soma == sum(valores)
