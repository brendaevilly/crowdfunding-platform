"""Cálculo puro dos percentuais de participação dos investidores."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

ESCALA_PERCENTUAL = 1_000_000


@dataclass(frozen=True)
class PercentualParticipacao:
    """Percentual calculado para um investidor."""

    investidor_id: str
    valor_aportado: int
    percentual_unidades: int


def calcular_participacoes(
    valores_por_investidor: Mapping[str, int],
) -> tuple[PercentualParticipacao, ...]:
    """Calcula percentuais proporcionais usando o método do maior resto."""

    if not valores_por_investidor:
        raise ValueError("É necessário informar ao menos um investidor")

    if any(valor <= 0 for valor in valores_por_investidor.values()):
        raise ValueError("Todos os aportes devem ser positivos")

    total = sum(valores_por_investidor.values())

    partes: list[tuple[str, int, int, int]] = []

    for investidor_id, valor in sorted(valores_por_investidor.items()):
        numerador = valor * ESCALA_PERCENTUAL
        unidades = numerador // total
        resto = numerador % total

        partes.append((investidor_id, valor, unidades, resto))

    unidades_distribuidas = sum(parte[2] for parte in partes)
    unidades_restantes = ESCALA_PERCENTUAL - unidades_distribuidas

    ordem_maior_resto = sorted(
        range(len(partes)),
        key=lambda indice: (-partes[indice][3], partes[indice][0]),
    )

    ajustes = set(ordem_maior_resto[:unidades_restantes])

    resultado = tuple(
        PercentualParticipacao(
            investidor_id=investidor_id,
            valor_aportado=valor,
            percentual_unidades=unidades + (1 if indice in ajustes else 0),
        )
        for indice, (investidor_id, valor, unidades, _) in enumerate(partes)
    )

    if sum(item.percentual_unidades for item in resultado) != ESCALA_PERCENTUAL:
        raise ValueError("A soma dos percentuais deve ser exatamente 100%")

    return resultado
