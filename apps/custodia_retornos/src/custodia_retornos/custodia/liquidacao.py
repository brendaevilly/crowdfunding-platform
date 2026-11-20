"""Regras financeiras puras para liquidação de campanhas."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class ValoresLiquidacao:
    valor_bruto: int
    taxa_plataforma: int
    valor_liquido: int


def calcular_liquidacao(
    valor_bruto: int,
    percentual_taxa: Decimal,
) -> ValoresLiquidacao:
    """Calcula taxa e líquido utilizando centavos inteiros."""

    if valor_bruto < 0:
        raise ValueError("Valor bruto não pode ser negativo")

    if not Decimal("0") <= percentual_taxa <= Decimal("100"):
        raise ValueError("Taxa deve estar entre 0 e 100")

    taxa = int(
        (Decimal(valor_bruto) * percentual_taxa / Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )

    liquido = valor_bruto - taxa

    return ValoresLiquidacao(
        valor_bruto=valor_bruto,
        taxa_plataforma=taxa,
        valor_liquido=liquido,
    )
