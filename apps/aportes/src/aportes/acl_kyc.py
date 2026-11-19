"""Anticorruption Layer entre o KYC e o domínio de Aportes."""

import sqlite3
from dataclasses import dataclass
from typing import Any

from contracts.eventos import IdentidadeVerificada


@dataclass(frozen=True)
class InvestidorVerificado:
    """Representação interna da verificação de um investidor."""

    usuario_id: str
    verificado: bool


def traduzir_identidade_verificada(
    payload: dict[str, Any],
) -> InvestidorVerificado:
    """Traduz o contrato externo para o vocabulário de Aportes."""
    evento = IdentidadeVerificada.model_validate(payload)

    return InvestidorVerificado(
        usuario_id=evento.usuario_id,
        verificado=True,
    )


def consumir_identidade_verificada(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> None:
    """Consome a verificação e registra o investidor uma única vez."""
    investidor = traduzir_identidade_verificada(payload)

    if not investidor.verificado:
        return

    conn.execute(
        """
        INSERT INTO investidor_verificado (investidor_id)
        VALUES (?)
        ON CONFLICT(investidor_id) DO NOTHING
        """,
        (investidor.usuario_id,),
    )
