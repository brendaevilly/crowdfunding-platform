"""Política de limite de aporte com verificação de investidor."""

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from aportes.domain import Valor
from shared.db import transaction

LIMITE_PADRAO_CENTAVOS = 100_000


@dataclass(frozen=True)
class PoliticaLimiteAporte:
    """Exige verificação para aportes acima do limite configurado."""

    limite_centavos: int = LIMITE_PADRAO_CENTAVOS

    def __post_init__(self) -> None:
        if type(self.limite_centavos) is not int:
            raise TypeError("O limite deve ser um inteiro em centavos")
        if self.limite_centavos < 0:
            raise ValueError("O limite não pode ser negativo")

    @classmethod
    def from_env(cls) -> "PoliticaLimiteAporte":
        """Obtém o limite pela variável LIMITE_APORTE_CENTAVOS."""
        valor = os.environ.get(
            "LIMITE_APORTE_CENTAVOS",
            str(LIMITE_PADRAO_CENTAVOS),
        )

        try:
            limite = int(valor)
        except ValueError as exc:
            raise ValueError("LIMITE_APORTE_CENTAVOS deve ser um inteiro") from exc

        return cls(limite_centavos=limite)

    def permite(self, valor: Valor, verificado: bool) -> bool:
        """Aplica a regra de limite e verificação."""
        if valor.centavos <= self.limite_centavos:
            return True

        return verificado is True

    def validar(self, valor: Valor, verificado: bool) -> None:
        """Rejeita aportes que exigem verificação não comprovada."""
        if not self.permite(valor, verificado):
            raise ValueError("Aporte acima do limite exige investidor verificado")


def investidor_esta_verificado(
    investidor_id: str,
    data_dir: str | Path = "data",
) -> bool:
    """Consulta a verificação; ausência de registro significa False."""

    def consultar(conn: sqlite3.Connection) -> bool:
        registro = conn.execute(
            """
            SELECT 1
            FROM investidor_verificado
            WHERE investidor_id = ?
            """,
            (investidor_id,),
        ).fetchone()

        return registro is not None

    return transaction(consultar, "aportes", data_dir)


def validar_limite_aporte(
    investidor_id: str,
    valor: Valor,
    data_dir: str | Path = "data",
    politica: PoliticaLimiteAporte | None = None,
) -> None:
    """Valida o aporte usando o estado persistido do investidor."""
    regra = politica if politica is not None else PoliticaLimiteAporte.from_env()

    if valor.centavos <= regra.limite_centavos:
        return

    verificado = investidor_esta_verificado(investidor_id, data_dir)
    regra.validar(valor, verificado)
