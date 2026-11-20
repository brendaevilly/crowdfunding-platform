"""Apuração idempotente de campanhas com outbox transacional."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from contracts.eventos import ResultadoCampanha, ResultadoFinal
from contracts.topicos import RESULTADO_CAMPANHA
from custodia_retornos.custodia.clock import Clock
from shared.db import transaction
from shared.outbox import OutboxEvent, add

SERVICE = "custodia_retornos"

logger = logging.getLogger(__name__)


def apurar_pendentes(
    clock: Clock,
    data_dir: str | Path = "data",
) -> int:
    """Apura campanhas vencidas ainda sem resultado.

    A inserção do resultado e o evento na outbox são atômicos.
    BEGIN IMMEDIATE serializa escritores SQLite concorrentes.
    """

    instante = clock.now()
    if instante.tzinfo is None:
        raise ValueError("Clock deve retornar data com fuso horário")

    instante_utc = instante.astimezone(UTC)

    def executar(conn: sqlite3.Connection) -> int:
        linhas = conn.execute(
            """
            SELECT c.campanha_id, c.empreendedor_id,
                   c.meta, c.saldo_retido, c.prazo_fim
            FROM custodia_contas c
            LEFT JOIN custodia_resultados r
                ON r.campanha_id = c.campanha_id
            WHERE r.campanha_id IS NULL
            ORDER BY c.campanha_id
            """
        ).fetchall()

        quantidade = 0

        for campanha_id, empreendedor_id, meta, saldo, prazo_fim in linhas:
            prazo = datetime.fromisoformat(str(prazo_fim))
            if prazo.tzinfo is None:
                raise ValueError(f"Campanha {campanha_id} possui prazo sem fuso horário")

            if prazo.astimezone(UTC) > instante_utc:
                continue

            if not empreendedor_id:
                logger.warning(
                    "Campanha %s vencida sem empreendedor_id; "
                    "apuração adiada até regularização dos dados.",
                    campanha_id,
                )
                continue

            investidores = tuple(
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT investidor_id
                    FROM custodia_investidores
                    WHERE campanha_id = ?
                    ORDER BY investidor_id
                    """,
                    (campanha_id,),
                )
            )

            resultado = ResultadoFinal.SUCESSO if int(saldo) >= int(meta) else ResultadoFinal.FALHA

            evento = ResultadoCampanha(
                campanha_id=str(campanha_id),
                empreendedor_id=str(empreendedor_id),
                resultado=resultado,
                valor_arrecadado=int(saldo),
                investidor_ids=investidores,
                encerrada_em=instante_utc,
            )

            cursor = conn.execute(
                """
                INSERT INTO custodia_resultados (
                    campanha_id, resultado, valor_arrecadado, encerrada_em
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(campanha_id) DO NOTHING
                """,
                (
                    campanha_id,
                    resultado.value,
                    int(saldo),
                    instante_utc.isoformat(),
                ),
            )

            if cursor.rowcount != 1:
                continue

            add(
                conn,
                OutboxEvent(
                    agregado_id=str(campanha_id),
                    tipo_evento=RESULTADO_CAMPANHA,
                    payload=evento.model_dump(
                        by_alias=True,
                        mode="json",
                    ),
                    correlation_id=str(campanha_id),
                ),
            )

            quantidade += 1

        return quantidade

    return transaction(executar, SERVICE, data_dir)
