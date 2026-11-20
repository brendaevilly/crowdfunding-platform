"""Rateio de retornos financeiros em centavos."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

ESCALA_PERCENTUAL = 1_000_000


@dataclass(frozen=True)
class ValorDistribuido:
    """Valor recebido por um investidor."""

    investidor_id: str
    valor: int


def calcular_distribuicao(
    valor_total: int,
    percentuais: Mapping[str, int],
) -> tuple[ValorDistribuido, ...]:
    """Distribui o valor proporcionalmente usando o método do maior resto."""

    if valor_total <= 0:
        raise ValueError("O valor total deve ser positivo")

    if not percentuais:
        raise ValueError("É necessário informar participações")

    if any(not investidor_id for investidor_id in percentuais):
        raise ValueError("Investidor inválido")

    if any(
        isinstance(unidades, bool) or not isinstance(unidades, int) or unidades < 0
        for unidades in percentuais.values()
    ):
        raise ValueError("Percentuais devem ser inteiros não negativos")

    if sum(percentuais.values()) != ESCALA_PERCENTUAL:
        raise ValueError("A soma dos percentuais deve ser exatamente 100%")

    partes: list[tuple[str, int, int]] = []

    for investidor_id, unidades in sorted(percentuais.items()):
        numerador = valor_total * unidades
        valor = numerador // ESCALA_PERCENTUAL
        resto = numerador % ESCALA_PERCENTUAL

        partes.append((investidor_id, valor, resto))

    centavos_restantes = valor_total - sum(parte[1] for parte in partes)

    ordem_maior_resto = sorted(
        range(len(partes)),
        key=lambda indice: (
            -partes[indice][2],
            partes[indice][0],
        ),
    )

    ajustes = set(ordem_maior_resto[:centavos_restantes])

    resultado = tuple(
        ValorDistribuido(
            investidor_id=investidor_id,
            valor=valor + (1 if indice in ajustes else 0),
        )
        for indice, (investidor_id, valor, _) in enumerate(partes)
    )

    if sum(item.valor for item in resultado) != valor_total:
        raise ValueError("A soma distribuída deve ser igual ao valor informado")

    return resultado
