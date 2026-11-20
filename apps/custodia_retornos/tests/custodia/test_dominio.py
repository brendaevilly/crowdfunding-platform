"""Testes das regras puras do domínio de custódia."""

from datetime import UTC, datetime

import pytest

from custodia_retornos.custodia.dominio import (
    ContaCustodia,
    Movimentacao,
    TipoMovimentacao,
    calcular_saldo,
)


def test_abrir_conta_custodia() -> None:
    conta = ContaCustodia.abrir(
        campanha_id="campanha-1",
        meta=100_000,
        prazo_fim=datetime(2026, 12, 31, tzinfo=UTC),
    )

    assert conta.campanha_id == "campanha-1"
    assert conta.meta == 100_000
    assert conta.saldo_retido == 0


def test_nao_permite_meta_negativa() -> None:
    with pytest.raises(ValueError):
        ContaCustodia.abrir(
            "campanha-1",
            -100,
            datetime.now(UTC),
        )


def test_nao_permite_prazo_sem_fuso() -> None:
    with pytest.raises(ValueError):
        ContaCustodia.abrir(
            "campanha-1",
            1000,
            datetime(2026, 12, 31),
        )


def test_criar_retencao() -> None:
    movimentacao = Movimentacao.criar_retencao(
        campanha_id="campanha-1",
        aporte_id="aporte-1",
        valor=5000,
    )

    assert movimentacao.tipo == TipoMovimentacao.RETENCAO
    assert movimentacao.valor == 5000
    assert movimentacao.aporte_id == "aporte-1"


def test_nao_permite_retencao_zero() -> None:
    with pytest.raises(ValueError):
        Movimentacao.criar_retencao(
            "campanha-1",
            "aporte-1",
            0,
        )


def test_calcular_saldo_das_retencoes() -> None:
    primeira = Movimentacao.criar_retencao("c1", "a1", 5000)
    segunda = Movimentacao.criar_retencao("c1", "a2", 3000)

    assert calcular_saldo((primeira, segunda)) == 8000


def test_calcular_saldo_com_devolucao() -> None:
    retencao = Movimentacao.criar_retencao("c1", "a1", 5000)

    devolucao = Movimentacao(
        movimentacao_id="m2",
        campanha_id="c1",
        aporte_id="a1",
        tipo=TipoMovimentacao.DEVOLUCAO,
        valor=2000,
        criada_em=datetime.now(UTC),
    )

    assert calcular_saldo((retencao, devolucao)) == 3000


def test_nao_permite_saldo_negativo() -> None:
    devolucao = Movimentacao(
        movimentacao_id="m1",
        campanha_id="c1",
        aporte_id="a1",
        tipo=TipoMovimentacao.DEVOLUCAO,
        valor=1000,
        criada_em=datetime.now(UTC),
    )

    with pytest.raises(ValueError):
        calcular_saldo((devolucao,))
