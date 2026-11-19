"""Reconciliação de aportes confirmados com retenção pendente."""

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.db import transaction

SERVICO = "aportes"
PRAZO_PADRAO_MINUTOS = 15


@dataclass(frozen=True)
class ResultadoReconciliacao:
    """Resultado de uma execução da rotina de reconciliação."""

    pendencias_sinalizadas: int
    prazo_minutos: int


def obter_prazo_reconciliacao() -> int:
    """Obtém o prazo configurado por variável de ambiente."""
    valor = os.getenv(
        "APORTES_RECONCILIACAO_MINUTOS",
        str(PRAZO_PADRAO_MINUTOS),
    )

    try:
        prazo = int(valor)
    except ValueError as exc:
        raise ValueError("APORTES_RECONCILIACAO_MINUTOS deve ser um inteiro positivo") from exc

    if prazo <= 0:
        raise ValueError("APORTES_RECONCILIACAO_MINUTOS deve ser maior que zero")

    return prazo


def reconciliar_aportes(
    *,
    data_dir: str | Path = "data",
    prazo_minutos: int | None = None,
    agora: datetime | None = None,
) -> ResultadoReconciliacao:
    """Sinaliza pendências de retenção que ultrapassaram o prazo.

    A rotina é idempotente: pendências já sinalizadas não são
    sinalizadas novamente.

    O status financeiro do aporte não é alterado.
    """
    prazo = prazo_minutos if prazo_minutos is not None else obter_prazo_reconciliacao()

    if prazo <= 0:
        raise ValueError("O prazo de reconciliação deve ser positivo")

    instante = agora if agora is not None else datetime.now(UTC)

    if instante.tzinfo is None or instante.utcoffset() is None:
        raise ValueError("O instante deve conter informação de fuso horário")

    instante_utc = instante.astimezone(UTC)
    limite = instante_utc - timedelta(minutes=prazo)

    # SQLite CURRENT_TIMESTAMP usa UTC no formato YYYY-MM-DD HH:MM:SS.
    limite_sql = limite.strftime("%Y-%m-%d %H:%M:%S")
    agora_sql = instante_utc.strftime("%Y-%m-%d %H:%M:%S")

    def operacao(conn: sqlite3.Connection) -> int:
        cursor = conn.execute(
            """
            UPDATE aporte_custodia
            SET sinalizado_em = ?
            WHERE status = 'PENDENTE'
              AND sinalizado_em IS NULL
              AND criado_em <= ?
              AND aporte_id IN (
                  SELECT id
                  FROM aporte
                  WHERE status = 'CONFIRMADO'
              )
            """,
            (agora_sql, limite_sql),
        )

        return cursor.rowcount

    quantidade = transaction(
        operacao,
        SERVICO,
        data_dir,
    )

    return ResultadoReconciliacao(
        pendencias_sinalizadas=quantidade,
        prazo_minutos=prazo,
    )
