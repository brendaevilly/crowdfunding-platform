"""Utilitários para valores monetários em centavos."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def to_cents(value: str | Decimal) -> int:
    """Converte um valor monetário em centavos inteiros.

    Exemplo:
        to_cents("25.90") -> 2590
    """
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Valor monetário inválido") from exc

    if not amount.is_finite():
        raise ValueError("Valor monetário deve ser finito")

    cents = (amount * 100).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )

    return int(cents)


def from_cents(cents: int) -> Decimal:
    """Converte centavos inteiros em valor decimal.

    Exemplo:
        from_cents(2590) -> Decimal("25.90")
    """
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise TypeError("Centavos devem ser um número inteiro")

    return (Decimal(cents) / Decimal("100")).quantize(Decimal("0.01"))
