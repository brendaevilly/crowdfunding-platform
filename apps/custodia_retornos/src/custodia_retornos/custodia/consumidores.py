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

    conn.execute(
        """
        UPDATE custodia_contas
        SET empreendedor_id = ?
        WHERE campanha_id = ?
          AND (empreendedor_id IS NULL OR empreendedor_id = ?)
        """,
        (
            evento.empreendedor_id,
            evento.campanha_id,
            evento.empreendedor_id,
        ),
    )
    if conn.execute("SELECT changes()").fetchone()[0] != 1:
        raise ValueError("Empreendedor divergente para a campanha")

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

    retencao_existente = conn.execute(
        """
        SELECT 1
        FROM custodia_movimentacoes
        WHERE aporte_id = ?
          AND campanha_id = ?
          AND tipo = 'RETENCAO'
        """,
        (evento.aporte_id, evento.campanha_id),
    ).fetchone()

    if retencao_existente is not None:
        logger.info(
            "Aporte %s já registrado; evento duplicado ignorado.",
            evento.aporte_id,
        )
        return

    resultado_existente = conn.execute(
        """
        SELECT 1
        FROM custodia_resultados
        WHERE campanha_id = ?
        """,
        (evento.campanha_id,),
    ).fetchone()

    if resultado_existente is not None:
        raise ValueError(
            f"Campanha {evento.campanha_id} já foi apurada; novos aportes não podem ser retidos"
        )

    movimentacao = Movimentacao.criar_retencao(
        campanha_id=evento.campanha_id,
        aporte_id=evento.aporte_id,
        valor=evento.valor,
    )

    registrada = registrar_movimentacao(conn, movimentacao)

    if registrada:
        conn.execute(
            """
            INSERT INTO custodia_investidores (
                campanha_id, investidor_id
            )
            VALUES (?, ?)
            ON CONFLICT(campanha_id, investidor_id) DO NOTHING
            """,
            (evento.campanha_id, evento.investidor_id),
        )
        logger.info(
            "Retenção de %d centavos registrada para o aporte %s.",
            evento.valor,
            evento.aporte_id,
        )


def consumir_resultado_campanha(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> None:
    """Executa a liquidação quando a campanha é apurada."""

    from decimal import Decimal

    from contracts.eventos import ResultadoCampanha
    from custodia_retornos.config import percentual_taxa_padrao
    from custodia_retornos.custodia.servico_liquidacao import liquidar_campanha

    evento = ResultadoCampanha.model_validate(payload)

    liquidar_campanha(
        conn,
        evento.campanha_id,
        Decimal(percentual_taxa_padrao()),
        agora=evento.encerrada_em,
    )

    logger.info(
        "Liquidação processada para campanha %s: %s",
        evento.campanha_id,
        evento.resultado.value,
    )
