"""Consumidores de eventos assíncronos emitidos pelo domínio de Pagamentos/Custódia."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from typing import Any

from contracts.eventos import ResultadoCampanha, TotalArrecadadoAtualizado

logger = logging.getLogger(__name__)


def consumir_total_arrecadado_atualizado(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> None:
    """Atualiza o total arrecadado da campanha de forma monotônica (estritamente crescente).

    Se o valor informado for menor ou igual ao já registrado (ex.: evento antigo fora de ordem),
    ele é ignorado sem disparar erro ou rollback.
    """
    evento = TotalArrecadadoAtualizado.model_validate(payload)
    agora_iso = datetime.now(UTC).isoformat()

    # Executa UPDATE atômico apenas se o novo valor for estritamente maior
    cursor = conn.execute(
        """
        UPDATE campanhas
        SET valor_arrecadado = ?, atualizado_em = ?
        WHERE id = ? AND ? > valor_arrecadado
        """,
        (evento.valor_acumulado, agora_iso, evento.campanha_id, evento.valor_acumulado),
    )

    if cursor.rowcount > 0:
        logger.info(
            "Total arrecadado da campanha %s atualizado para %d centavos.",
            evento.campanha_id,
            evento.valor_acumulado,
        )
    else:
        logger.debug(
            "Evento TotalArrecadadoAtualizado para campanha %s ignorado "
            "(valor %d menor ou igual ao já registrado ou campanha não encontrada).",
            evento.campanha_id,
            evento.valor_acumulado,
        )


def consumir_resultado_campanha(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> None:
    """Transiciona a campanha de PUBLICADA para ENCERRADA com base no resultado da custódia.

    Idempotente por campanhaId: se a campanha já se encontrar ENCERRADA, um segundo
    evento atua como no-op sem gerar erro.
    """
    evento = ResultadoCampanha.model_validate(payload)

    row = conn.execute(
        "SELECT status, valor_arrecadado FROM campanhas WHERE id = ?",
        (evento.campanha_id,),
    ).fetchone()

    if row is None:
        logger.warning(
            "Campanha %s não encontrada ao consumir ResultadoCampanha.",
            evento.campanha_id,
        )
        return

    status_atual: str = row[0]
    valor_atual: int = row[1]

    if status_atual == "ENCERRADA":
        logger.info(
            "Campanha %s já se encontra ENCERRADA. Evento de resultado ignorado (idempotente).",
            evento.campanha_id,
        )
        return

    # Atualiza valor arrecadado se o valor do encerramento for maior
    novo_valor = max(valor_atual, evento.valor_arrecadado)
    encerrada_iso = evento.encerrada_em.isoformat()

    conn.execute(
        """
        UPDATE campanhas
        SET status = 'ENCERRADA',
            valor_arrecadado = ?,
            versao = versao + 1,
            atualizado_em = ?
        WHERE id = ?
        """,
        (novo_valor, encerrada_iso, evento.campanha_id),
    )
    logger.info(
        "Campanha %s encerrada com resultado %s.",
        evento.campanha_id,
        evento.resultado.value,
    )
