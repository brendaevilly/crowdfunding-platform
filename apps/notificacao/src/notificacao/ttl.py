"""Módulo de expiração de notificações antigas (job periódico estilo TTL)."""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from notificacao.repository import expirar_notificacoes_antigas
from shared.db import transaction

logger = logging.getLogger(__name__)

TTL_DIAS_PADRAO = 30
TTL_INTERVALO_PADRAO_SEGUNDOS = 3600.0


def obter_ttl_dias_padrao() -> int:
    """Retorna o TTL configurado em dias para retenção de notificações."""
    try:
        return int(os.getenv("NOTIFICACAO_TTL_DIAS", str(TTL_DIAS_PADRAO)))
    except ValueError:
        return TTL_DIAS_PADRAO


def obter_ttl_intervalo_padrao() -> float:
    """Retorna o intervalo de varredura do job TTL em segundos."""
    try:
        return float(
            os.getenv("NOTIFICACAO_TTL_INTERVALO_SEGUNDOS", str(TTL_INTERVALO_PADRAO_SEGUNDOS))
        )
    except ValueError:
        return TTL_INTERVALO_PADRAO_SEGUNDOS


def limpar_notificacoes_expiradas(
    data_dir: str | Path = "data",
    dias_ttl: int | None = None,
) -> int:
    """Executa a limpeza atômica de notificações expiradas com idade superior ao TTL configurado.

    Retorna o número de registros removidos.
    """
    dias = dias_ttl if dias_ttl is not None else obter_ttl_dias_padrao()

    def operacao(conn: sqlite3.Connection) -> int:
        return expirar_notificacoes_antigas(conn, dias)

    removidos = transaction(operacao, "notificacao", data_dir)
    if removidos > 0:
        logger.info(
            "Limpeza TTL concluída: %d notificações anteriores a %d dias foram removidas.",
            removidos,
            dias,
        )
    return removidos


def run_ttl_cleaner(
    data_dir: str | Path = "data",
    *,
    dias_ttl: int | None = None,
    intervalo_segundos: float | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Loop contínuo do job de limpeza periódica de notificações expiradas."""
    intervalo = (
        intervalo_segundos if intervalo_segundos is not None else obter_ttl_intervalo_padrao()
    )
    dias = dias_ttl if dias_ttl is not None else obter_ttl_dias_padrao()
    stop_check = should_stop or (lambda: False)

    logger.info(
        "Iniciando job de limpeza TTL de notificações (TTL=%d dias, intervalo=%.1fs)",
        dias,
        intervalo,
    )

    while not stop_check():
        try:
            limpar_notificacoes_expiradas(data_dir=data_dir, dias_ttl=dias)
        except Exception:
            logger.exception("Erro ao executar ciclo do job de limpeza TTL")

        # Espera granular para resposta rápida ao pedido de interrupção
        passo = 0.5
        tempo_decorrido = 0.0
        while tempo_decorrido < intervalo and not stop_check():
            time.sleep(min(passo, intervalo - tempo_decorrido))
            tempo_decorrido += passo

    logger.info("Job de limpeza TTL de notificações finalizado.")
