"""Serviço transacional de liquidação e devolução de campanhas."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from contracts.eventos import CampanhaLiquidada
from contracts.topicos import CAMPANHA_LIQUIDADA
from custodia_retornos.custodia.dominio import (
    Movimentacao,
    TipoMovimentacao,
)
from custodia_retornos.custodia.liquidacao import calcular_liquidacao
from custodia_retornos.custodia.repositorio import registrar_movimentacao
from shared.db import transaction
from shared.outbox import OutboxEvent, add


def liquidar_campanha(
    conn: sqlite3.Connection,
    campanha_id: str,
    percentual_taxa: Decimal,
    agora: datetime | None = None,
) -> bool:
    """Liquida uma campanha uma única vez, dentro da transação recebida."""

    if agora is None:
        agora = datetime.now(UTC)

    if agora.tzinfo is None:
        raise ValueError("A data de liquidação deve possuir fuso horário")

    campanha = conn.execute(
        """
        SELECT r.resultado, c.saldo_retido, c.empreendedor_id
        FROM custodia_resultados r
        JOIN custodia_contas c ON c.campanha_id = r.campanha_id
        WHERE r.campanha_id = ?
        """,
        (campanha_id,),
    ).fetchone()

    if campanha is None:
        raise ValueError("Resultado da campanha não encontrado")

    resultado = str(campanha[0])
    saldo = int(campanha[1])

    existente = conn.execute(
        """
        SELECT 1 FROM custodia_liquidacoes
        WHERE campanha_id = ?
        """,
        (campanha_id,),
    ).fetchone()

    if existente is not None:
        return False

    aportes = conn.execute(
        """
        SELECT aporte_id, valor
        FROM custodia_movimentacoes
        WHERE campanha_id = ?
          AND tipo = 'RETENCAO'
        ORDER BY aporte_id
        """,
        (campanha_id,),
    ).fetchall()

    total_aportes = sum(int(aporte[1]) for aporte in aportes)

    if total_aportes != saldo:
        raise ValueError("Saldo retido diverge da soma das retenções")

    if resultado == "SUCESSO":
        valores = calcular_liquidacao(saldo, percentual_taxa)
        taxa = valores.taxa_plataforma
        liquido = valores.valor_liquido
    elif resultado == "FALHA":
        taxa = 0
        liquido = 0
    else:
        raise ValueError("Resultado de campanha inválido")

    liquidada_em = agora.isoformat()

    conn.execute(
        """
        INSERT INTO custodia_liquidacoes (
            campanha_id, resultado, valor_bruto,
            taxa_plataforma, valor_liquido, liquidada_em
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            campanha_id,
            resultado,
            saldo,
            taxa,
            liquido,
            liquidada_em,
        ),
    )

    if resultado == "SUCESSO":
        if liquido > 0:
            movimentacao = Movimentacao(
                movimentacao_id=str(uuid4()),
                campanha_id=campanha_id,
                aporte_id=None,
                tipo=TipoMovimentacao.LIBERACAO,
                valor=liquido,
                criada_em=agora,
            )
            registrar_movimentacao(conn, movimentacao)

        conn.execute(
            """
            INSERT INTO custodia_taxas (
                campanha_id, valor, criada_em
            )
            VALUES (?, ?, ?)
            """,
            (campanha_id, taxa, liquidada_em),
        )

        if taxa > 0:
            movimentacao_taxa = Movimentacao(
                movimentacao_id=str(uuid4()),
                campanha_id=campanha_id,
                aporte_id=None,
                tipo=TipoMovimentacao.TAXA,
                valor=taxa,
                criada_em=agora,
            )
            registrar_movimentacao(conn, movimentacao_taxa)

        evento = CampanhaLiquidada(
            campanha_id=campanha_id,
            valor_bruto=saldo,
            taxa_plataforma=taxa,
            valor_liquido=liquido,
            aportes=tuple(str(aporte[0]) for aporte in aportes),
            liquidada_em=agora,
        )

        add(
            conn,
            OutboxEvent(
                agregado_id=campanha_id,
                tipo_evento=CAMPANHA_LIQUIDADA,
                payload=evento.model_dump(mode="json", by_alias=True),
                correlation_id=campanha_id,
            ),
        )

    else:
        for aporte_id, valor in aportes:
            devolucao = Movimentacao(
                movimentacao_id=str(uuid4()),
                campanha_id=campanha_id,
                aporte_id=str(aporte_id),
                tipo=TipoMovimentacao.DEVOLUCAO,
                valor=int(valor),
                criada_em=agora,
            )
            registrar_movimentacao(conn, devolucao)

    conta = conn.execute(
        """
        SELECT saldo_retido
        FROM custodia_contas
        WHERE campanha_id = ?
        """,
        (campanha_id,),
    ).fetchone()

    if conta is None or int(conta[0]) != 0:
        raise ValueError("A liquidação não zerou o saldo da custódia")

    return True


def executar_liquidacao(
    campanha_id: str,
    percentual_taxa: Decimal,
    data_dir: str = "data",
) -> bool:
    """Executa e confirma a liquidação em uma única transação."""

    return transaction(
        lambda conn: liquidar_campanha(
            conn,
            campanha_id,
            percentual_taxa,
        ),
        "custodia_retornos",
        data_dir,
    )
