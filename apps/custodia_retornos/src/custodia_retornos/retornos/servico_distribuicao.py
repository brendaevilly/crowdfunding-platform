"""Serviço de distribuição financeira dos retornos."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from contracts.eventos import RetornoDistribuido
from contracts.topicos import RETORNO_DISTRIBUIDO
from custodia_retornos.retornos.distribuicao import (
    ESCALA_PERCENTUAL,
    calcular_distribuicao,
)
from shared.outbox import OutboxEvent, add


def distribuir_retornos(
    conn: sqlite3.Connection,
    campanha_id: str,
    empreendedor_id: str,
    valor_total: int,
) -> list[dict[str, str | int]]:
    """Distribui retornos proporcionalmente e registra eventos na outbox."""

    if valor_total <= 0:
        raise ValueError("O valor da distribuição deve ser positivo")

    conta = conn.execute(
        """
        SELECT empreendedor_id
        FROM custodia_contas
        WHERE campanha_id = ?
        """,
        (campanha_id,),
    ).fetchone()

    if conta is None:
        raise ValueError("Campanha não encontrada")

    if str(conta[0]) != empreendedor_id:
        raise PermissionError("Empreendedor não é dono da campanha")

    liquidacao = conn.execute(
        """
        SELECT resultado
        FROM custodia_liquidacoes
        WHERE campanha_id = ?
        """,
        (campanha_id,),
    ).fetchone()

    if liquidacao is None or str(liquidacao[0]) != "SUCESSO":
        raise ValueError(
            "Não é permitido distribuir retornos de campanha não liquidada com sucesso"
        )

    registros = conn.execute(
        """
        SELECT investidor_id, percentual_unidades
        FROM retornos_participacoes
        WHERE campanha_id = ?
        ORDER BY investidor_id
        """,
        (campanha_id,),
    ).fetchall()

    if not registros:
        raise ValueError("Campanha não possui participações")

    percentuais = {str(investidor_id): int(unidades) for investidor_id, unidades in registros}

    if sum(percentuais.values()) != ESCALA_PERCENTUAL:
        raise ValueError("A soma das participações deve ser exatamente 100%")

    valores = calcular_distribuicao(valor_total, percentuais)

    lote_id = str(uuid4())
    distribuido_em = datetime.now(UTC)

    conn.execute(
        """
        INSERT INTO retornos_lotes_distribuicao (
            lote_id,
            campanha_id,
            empreendedor_id,
            valor_total,
            distribuido_em
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            lote_id,
            campanha_id,
            empreendedor_id,
            valor_total,
            distribuido_em.isoformat(),
        ),
    )

    resultado: list[dict[str, str | int]] = []

    for item in valores:
        if item.valor == 0:
            continue

        retorno_id = str(uuid4())

        conn.execute(
            """
            INSERT INTO retornos_distribuicao_itens (
                retorno_id,
                lote_id,
                campanha_id,
                investidor_id,
                valor,
                distribuido_em
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                retorno_id,
                lote_id,
                campanha_id,
                item.investidor_id,
                item.valor,
                distribuido_em.isoformat(),
            ),
        )

        evento = RetornoDistribuido(
            retorno_id=retorno_id,
            campanha_id=campanha_id,
            investidor_id=item.investidor_id,
            valor=item.valor,
            evento_origem_id=lote_id,
            distribuido_em=distribuido_em,
        )

        add(
            conn,
            OutboxEvent(
                agregado_id=campanha_id,
                tipo_evento=RETORNO_DISTRIBUIDO,
                payload=evento.model_dump(
                    by_alias=True,
                    mode="json",
                ),
                correlation_id=campanha_id,
            ),
        )

        resultado.append(
            {
                "retornoId": retorno_id,
                "investidorId": item.investidor_id,
                "valor": item.valor,
            }
        )

    if sum(item["valor"] for item in resultado if isinstance(item["valor"], int)) != valor_total:
        raise ValueError("A soma das distribuições diverge do valor informado")

    return resultado


def listar_extrato_investidor(
    conn: sqlite3.Connection,
    investidor_id: str,
) -> list[dict[str, object]]:
    """Lista os retornos recebidos exclusivamente pelo investidor."""

    registros = conn.execute(
        """
        SELECT
            retorno_id,
            campanha_id,
            valor,
            distribuido_em
        FROM retornos_distribuicao_itens
        WHERE investidor_id = ?
        ORDER BY distribuido_em DESC, retorno_id
        """,
        (investidor_id,),
    ).fetchall()

    return [
        {
            "retornoId": str(retorno_id),
            "campanhaId": str(campanha_id),
            "valor": int(valor),
            "distribuidoEm": str(distribuido_em),
        }
        for retorno_id, campanha_id, valor, distribuido_em in registros
    ]
