"""Serviço de criação das participações dos investidores."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any
from uuid import uuid4

from contracts.eventos import CampanhaLiquidada
from custodia_retornos.retornos.participacoes import calcular_participacoes


def criar_participacoes(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> bool:
    """Cria as participações de uma campanha liquidada uma única vez."""

    evento = CampanhaLiquidada.model_validate(payload)

    if not evento.aportes:
        raise ValueError("Campanha liquidada não possui aportes")

    if len(set(evento.aportes)) != len(evento.aportes):
        raise ValueError("Evento contém aportes duplicados")

    placeholders = ", ".join("?" for _ in evento.aportes)

    aportes = conn.execute(
        f"""
        SELECT aporte_id, investidor_id, valor
        FROM retornos_aportes
        WHERE campanha_id = ?
          AND aporte_id IN ({placeholders})
        """,
        (evento.campanha_id, *evento.aportes),
    ).fetchall()

    aportes_encontrados = {str(aporte[0]) for aporte in aportes}

    if aportes_encontrados != set(evento.aportes):
        raise ValueError("Existem aportes do evento que não foram registrados em Retornos")

    valores_por_investidor: dict[str, int] = defaultdict(int)

    for _, investidor_id, valor in aportes:
        valores_por_investidor[str(investidor_id)] += int(valor)

    total_aportado = sum(valores_por_investidor.values())

    if total_aportado != evento.valor_bruto:
        raise ValueError("A soma dos aportes diverge do valor bruto liquidado")

    participacoes = calcular_participacoes(valores_por_investidor)

    cursor = conn.execute(
        """
        INSERT INTO retornos_distribuicoes (
            distribuicao_id,
            campanha_id,
            criada_em
        )
        VALUES (?, ?, ?)
        ON CONFLICT(campanha_id) DO NOTHING
        """,
        (
            str(uuid4()),
            evento.campanha_id,
            evento.liquidada_em.isoformat(),
        ),
    )

    if cursor.rowcount != 1:
        return False

    for participacao in participacoes:
        conn.execute(
            """
            INSERT INTO retornos_participacoes (
                participacao_id,
                campanha_id,
                investidor_id,
                valor_aportado,
                percentual_unidades,
                criada_em
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                evento.campanha_id,
                participacao.investidor_id,
                participacao.valor_aportado,
                participacao.percentual_unidades,
                evento.liquidada_em.isoformat(),
            ),
        )

    soma_percentuais = sum(item.percentual_unidades for item in participacoes)

    if soma_percentuais != 1_000_000:
        raise ValueError("A soma das participações deve ser exatamente 100%")

    return True


def listar_participacoes_investidor(
    conn: sqlite3.Connection,
    investidor_id: str,
) -> list[dict[str, object]]:
    """Lista as participações exclusivamente de um investidor."""

    registros = conn.execute(
        """
        SELECT campanha_id, valor_aportado,
               percentual_unidades, criada_em
        FROM retornos_participacoes
        WHERE investidor_id = ?
        ORDER BY criada_em DESC, campanha_id
        """,
        (investidor_id,),
    ).fetchall()

    return [
        {
            "campanhaId": str(campanha_id),
            "valorAportado": int(valor),
            "percentual": f"{int(unidades) / 1_000_000:.4f}",
            "criadaEm": str(criada_em),
        }
        for campanha_id, valor, unidades, criada_em in registros
    ]


def consumir_campanha_liquidada(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> None:
    """Adapta a criação de participações ao contrato do consumidor."""
    criar_participacoes(conn, payload)
