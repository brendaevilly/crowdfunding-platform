"""Testes do cálculo de participações."""

import pytest

from custodia_retornos.retornos.participacoes import (
    ESCALA_PERCENTUAL,
    calcular_participacoes,
)


def test_calcula_percentuais_proporcionais() -> None:
    resultado = calcular_participacoes(
        {
            "investidor-1": 6000,
            "investidor-2": 4000,
        }
    )

    percentuais = {item.investidor_id: item.percentual_unidades for item in resultado}

    assert percentuais == {
        "investidor-1": 600000,
        "investidor-2": 400000,
    }


def test_soma_dos_percentuais_e_exatamente_100_por_cento() -> None:
    resultado = calcular_participacoes(
        {
            "investidor-1": 100,
            "investidor-2": 100,
            "investidor-3": 100,
        }
    )

    assert sum(item.percentual_unidades for item in resultado) == ESCALA_PERCENTUAL


def test_maior_resto_distribui_unidades_restantes() -> None:
    resultado = calcular_participacoes(
        {
            "investidor-1": 1,
            "investidor-2": 1,
            "investidor-3": 1,
        }
    )

    percentuais = {item.investidor_id: item.percentual_unidades for item in resultado}

    assert percentuais == {
        "investidor-1": 333334,
        "investidor-2": 333333,
        "investidor-3": 333333,
    }


def test_resultado_e_deterministico() -> None:
    primeiro = calcular_participacoes({"investidor-1": 10, "investidor-2": 20})

    segundo = calcular_participacoes({"investidor-2": 20, "investidor-1": 10})

    assert primeiro == segundo


@pytest.mark.parametrize(
    "valores",
    [
        {},
        {"investidor-1": 0},
        {"investidor-1": -100},
    ],
)
def test_rejeita_aportes_invalidos(
    valores: dict[str, int],
) -> None:
    with pytest.raises(ValueError):
        calcular_participacoes(valores)
