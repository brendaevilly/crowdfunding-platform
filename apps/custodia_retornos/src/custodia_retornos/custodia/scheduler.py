"""Scheduler periódico para apuração de campanhas."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from custodia_retornos.custodia.apuracao import apurar_pendentes
from custodia_retornos.custodia.clock import Clock

logger = logging.getLogger(__name__)


async def executar_scheduler(
    clock: Clock,
    data_dir: str | Path,
    intervalo: float = 5.0,
) -> None:
    if intervalo <= 0:
        raise ValueError("Intervalo deve ser positivo")

    while True:
        try:
            quantidade = await asyncio.to_thread(
                apurar_pendentes,
                clock,
                data_dir,
            )
            if quantidade:
                logger.info(
                    "Campanhas apuradas: %d",
                    quantidade,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erro no scheduler de custódia")

        await asyncio.sleep(intervalo)
