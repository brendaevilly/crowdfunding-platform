"""Consumidores dos eventos de Campanhas e Aportes."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from contracts.eventos import AporteConfirmado, CampanhaPublicada
from custodia_retornos.custodia.dominio import ContaCustodia, Movimentacao
from custodia_retornos.custodia.repositorio import (
    abrir_conta,
    buscar_conta,
    registrar_movimentacao,
)

logger = logging.getLogger(__name__)


class ContaCustodiaNaoEncontradaErro(RuntimeError):
    """A campanha ainda não possui uma conta de custódia."""


def consumir_campanha_publicada(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> None:
    """Abre uma conta de custódia para a campanha publicada."""

    evento = CampanhaPublicada.model_validate(payload)

    conta = ContaCustodia.abrir(
        campanha_id=evento.campanha_id,
        meta=evento.meta,
        prazo_fim=evento.prazo_fim,
    )

    criada = abrir_conta(conn, conta)

    if criada:
        logger.info(
            "Conta de custódia aberta para campanha %s.",
            evento.campanha_id,
        )


def consumir_aporte_confirmado(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> None:
    """Registra a retenção de um aporte de maneira idempotente."""

    evento = AporteConfirmado.model_validate(payload)

    conta = buscar_conta(conn, evento.campanha_id)

    if conta is None:
        raise ContaCustodiaNaoEncontradaErro(
            f"Conta de custódia da campanha {evento.campanha_id} ainda não foi aberta."
        )

    movimentacao = Movimentacao.criar_retencao(
        campanha_id=evento.campanha_id,
        aporte_id=evento.aporte_id,
        valor=evento.valor,
    )

    registrada = registrar_movimentacao(conn, movimentacao)

    if registrada:
        logger.info(
            "Retenção de %d centavos registrada para o aporte %s.",
            evento.valor,
            evento.aporte_id,
        )
