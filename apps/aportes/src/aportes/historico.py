"""Consultas de histórico e resumo de aportes."""

import sqlite3
from pathlib import Path
from typing import TypedDict

from shared.db import transaction


class ItemHistorico(TypedDict):
    aporteId: str
    campanhaId: str
    investidorId: str
    valor: int
    status: str
    criadoEm: str


class HistoricoPaginado(TypedDict):
    itens: list[ItemHistorico]
    pagina: int
    tamanhoPagina: int
    total: int
    totalPaginas: int


class ResumoCampanha(TypedDict):
    campanhaId: str
    total: int
    quantidade: int


def listar_aportes_investidor(
    *,
    investidor_id: str,
    pagina: int = 1,
    tamanho_pagina: int = 10,
    campanha_id: str | None = None,
    data_dir: str | Path = "data",
) -> HistoricoPaginado:
    """Lista exclusivamente os aportes do investidor informado."""

    if not investidor_id.strip():
        raise ValueError("O identificador do investidor é obrigatório")

    if pagina < 1:
        raise ValueError("A página deve ser maior ou igual a 1")

    if not 1 <= tamanho_pagina <= 100:
        raise ValueError("O tamanho da página deve estar entre 1 e 100")

    def consultar(conn: sqlite3.Connection) -> HistoricoPaginado:
        filtros = ["investidor_id = ?"]
        parametros: list[str | int] = [investidor_id]

        if campanha_id is not None:
            filtros.append("campanha_id = ?")
            parametros.append(campanha_id)

        where = " AND ".join(filtros)

        total = int(
            conn.execute(
                f"SELECT COUNT(*) FROM aporte WHERE {where}",
                parametros,
            ).fetchone()[0]
        )

        deslocamento = (pagina - 1) * tamanho_pagina

        registros = conn.execute(
            f"""
            SELECT
                id,
                campanha_id,
                investidor_id,
                valor,
                status,
                criado_em
            FROM aporte
            WHERE {where}
            ORDER BY criado_em DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            [*parametros, tamanho_pagina, deslocamento],
        ).fetchall()

        itens: list[ItemHistorico] = [
            {
                "aporteId": str(registro[0]),
                "campanhaId": str(registro[1]),
                "investidorId": str(registro[2]),
                "valor": int(registro[3]),
                "status": str(registro[4]),
                "criadoEm": str(registro[5]),
            }
            for registro in registros
        ]

        return {
            "itens": itens,
            "pagina": pagina,
            "tamanhoPagina": tamanho_pagina,
            "total": total,
            "totalPaginas": (total + tamanho_pagina - 1) // tamanho_pagina,
        }

    return transaction(consultar, "aportes", data_dir)


def obter_resumo_campanha(
    *,
    campanha_id: str,
    data_dir: str | Path = "data",
) -> ResumoCampanha:
    """Calcula total e quantidade de aportes confirmados da campanha."""

    if not campanha_id.strip():
        raise ValueError("O identificador da campanha é obrigatório")

    def consultar(conn: sqlite3.Connection) -> ResumoCampanha:
        registro = conn.execute(
            """
            SELECT
                COALESCE(SUM(valor), 0),
                COUNT(*)
            FROM aporte
            WHERE campanha_id = ?
              AND status = 'CONFIRMADO'
            """,
            (campanha_id,),
        ).fetchone()

        assert registro is not None

        return {
            "campanhaId": campanha_id,
            "total": int(registro[0]),
            "quantidade": int(registro[1]),
        }

    return transaction(consultar, "aportes", data_dir)
