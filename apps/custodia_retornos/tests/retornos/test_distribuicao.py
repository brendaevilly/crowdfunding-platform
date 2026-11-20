"""Testes do cálculo proporcional de distribuição de retornos."""

import pytest

from custodia_retornos.retornos.distribuicao import (
    calcular_distribuicao,
)


def test_distribui_valor_proporcionalmente() -> None:
    resultado = calcular_distribuicao(
        10000,
        {
            "investidor-1": 600000,
            "investidor-2": 400000,
        },
    )

    valores = {item.investidor_id: item.valor for item in resultado}

    assert valores == {
        "investidor-1": 6000,
        "investidor-2": 4000,
    }


def test_maior_resto_distribui_centavos_restantes() -> None:
    resultado = calcular_distribuicao(
        10000,
        {
            "investidor-1": 333333,
            "investidor-2": 333333,
            "investidor-3": 333334,
        },
    )

    valores = {item.investidor_id: item.valor for item in resultado}

    assert valores == {
        "investidor-1": 3333,
        "investidor-2": 3333,
        "investidor-3": 3334,
    }

    assert sum(valores.values()) == 10000


def test_soma_distribuida_e_igual_ao_total() -> None:
    resultado = calcular_distribuicao(
        12345,
        {
            "investidor-1": 500000,
            "investidor-2": 300000,
            "investidor-3": 200000,
        },
    )

    assert sum(item.valor for item in resultado) == 12345


def test_resultado_e_deterministico() -> None:
    participacoes = {
        "investidor-3": 333334,
        "investidor-1": 333333,
        "investidor-2": 333333,
    }

    primeira = calcular_distribuicao(10000, participacoes)
    segunda = calcular_distribuicao(10000, participacoes)

    assert primeira == segunda


@pytest.mark.parametrize(
    ("valor_total", "percentuais"),
    [
        (0, {"investidor-1": 1000000}),
        (-100, {"investidor-1": 1000000}),
        (10000, {}),
        (10000, {"investidor-1": 500000}),
        (10000, {"investidor-1": -1000000, "investidor-2": 2000000}),
        (10000, {"investidor-1": True, "investidor-2": 0}),
    ],
)
def test_rejeita_distribuicoes_invalidas(
    valor_total: int,
    percentuais: dict[str, int],
) -> None:
    with pytest.raises(ValueError):
        calcular_distribuicao(valor_total, percentuais)
