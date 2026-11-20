"""Persistência das contas e movimentações de custódia."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from custodia_retornos.custodia.dominio import (
    ContaCustodia,
    Movimentacao,
    TipoMovimentacao,
)


def abrir_conta(
    conn: sqlite3.Connection,
    conta: ContaCustodia,
) -> bool:
    """Abre uma conta uma única vez por campanha."""

    cursor = conn.execute(
        """
        INSERT INTO custodia_contas (
            campanha_id, meta, prazo_fim, saldo_retido
        )
        VALUES (?, ?, ?, 0)
        ON CONFLICT(campanha_id) DO NOTHING
        """,
        (
            conta.campanha_id,
            conta.meta,
            conta.prazo_fim.isoformat(),
        ),
    )

    return cursor.rowcount == 1


def buscar_conta(
    conn: sqlite3.Connection,
    campanha_id: str,
) -> ContaCustodia | None:
    linha = conn.execute(
        """
        SELECT campanha_id, meta, prazo_fim, saldo_retido
        FROM custodia_contas
        WHERE campanha_id = ?
        """,
        (campanha_id,),
    ).fetchone()

    if linha is None:
        return None

    return ContaCustodia(
        campanha_id=str(linha[0]),
        meta=int(linha[1]),
        prazo_fim=datetime.fromisoformat(str(linha[2])),
        saldo_retido=int(linha[3]),
    )


def registrar_movimentacao(
    conn: sqlite3.Connection,
    movimentacao: Movimentacao,
) -> bool:
    """Registra uma movimentação sem permitir duplicidade de retenção."""

    if movimentacao.tipo == TipoMovimentacao.RETENCAO:
        cursor = conn.execute(
            """
            INSERT INTO custodia_movimentacoes (
                movimentacao_id, campanha_id, aporte_id,
                tipo, valor, criada_em
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(aporte_id) WHERE tipo = 'RETENCAO'
            DO NOTHING
            """,
            (
                movimentacao.movimentacao_id,
                movimentacao.campanha_id,
                movimentacao.aporte_id,
                movimentacao.tipo.value,
                movimentacao.valor,
                movimentacao.criada_em.isoformat(),
            ),
        )
    else:
        cursor = conn.execute(
            """
            INSERT INTO custodia_movimentacoes (
                movimentacao_id, campanha_id, aporte_id,
                tipo, valor, criada_em
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                movimentacao.movimentacao_id,
                movimentacao.campanha_id,
                movimentacao.aporte_id,
                movimentacao.tipo.value,
                movimentacao.valor,
                movimentacao.criada_em.isoformat(),
            ),
        )

    if cursor.rowcount != 1:
        return False

    if movimentacao.tipo == TipoMovimentacao.RETENCAO:
        conn.execute(
            """
            UPDATE custodia_contas
            SET saldo_retido = saldo_retido + ?
            WHERE campanha_id = ?
            """,
            (movimentacao.valor, movimentacao.campanha_id),
        )
    else:
        conn.execute(
            """
            UPDATE custodia_contas
            SET saldo_retido = saldo_retido - ?
            WHERE campanha_id = ?
              AND saldo_retido >= ?
            """,
            (
                movimentacao.valor,
                movimentacao.campanha_id,
                movimentacao.valor,
            ),
        )

        if conn.execute("SELECT changes()").fetchone()[0] != 1:
            raise ValueError("Saldo insuficiente para movimentação")

    return True


def listar_movimentacoes(
    conn: sqlite3.Connection,
    campanha_id: str,
) -> tuple[Movimentacao, ...]:
    linhas = conn.execute(
        """
        SELECT movimentacao_id, campanha_id, aporte_id,
               tipo, valor, criada_em
        FROM custodia_movimentacoes
        WHERE campanha_id = ?
        ORDER BY criada_em, movimentacao_id
        """,
        (campanha_id,),
    ).fetchall()

    return tuple(
        Movimentacao(
            movimentacao_id=str(linha[0]),
            campanha_id=str(linha[1]),
            aporte_id=str(linha[2]) if linha[2] is not None else None,
            tipo=TipoMovimentacao(str(linha[3])),
            valor=int(linha[4]),
            criada_em=datetime.fromisoformat(str(linha[5])),
        )
        for linha in linhas
    )
