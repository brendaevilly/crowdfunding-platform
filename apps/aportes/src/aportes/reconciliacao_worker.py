"""Execução periódica da reconciliação de aportes."""

import asyncio
import logging
import os
from pathlib import Path

from aportes.reconciliacao import reconciliar_aportes

log = logging.getLogger(__name__)

INTERVALO_PADRAO_SEGUNDOS = 60


def obter_intervalo_reconciliacao() -> int:
    """Obtém o intervalo de execução configurado."""
    valor = os.getenv(
        "APORTES_RECONCILIACAO_INTERVALO_SEGUNDOS",
        str(INTERVALO_PADRAO_SEGUNDOS),
    )

    try:
        intervalo = int(valor)
    except ValueError as exc:
        raise ValueError(
            "APORTES_RECONCILIACAO_INTERVALO_SEGUNDOS deve ser um inteiro positivo"
        ) from exc

    if intervalo <= 0:
        raise ValueError("APORTES_RECONCILIACAO_INTERVALO_SEGUNDOS deve ser maior que zero")

    return intervalo


async def executar_reconciliacao_periodica(
    *,
    data_dir: str | Path = "data",
    intervalo_segundos: int | None = None,
) -> None:
    """Executa a reconciliação periodicamente até ser cancelada."""
    intervalo = (
        intervalo_segundos if intervalo_segundos is not None else obter_intervalo_reconciliacao()
    )

    if intervalo <= 0:
        raise ValueError("O intervalo de reconciliação deve ser positivo")

    while True:
        try:
            resultado = await asyncio.to_thread(
                reconciliar_aportes,
                data_dir=data_dir,
            )

            if resultado.pendencias_sinalizadas:
                log.warning(
                    "Reconciliação sinalizou %s pendência(s) de retenção",
                    resultado.pendencias_sinalizadas,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Erro durante a reconciliação de aportes")

        await asyncio.sleep(intervalo)
