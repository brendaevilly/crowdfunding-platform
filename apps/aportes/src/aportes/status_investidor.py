"""Estado local do investidor atualizado por eventos de Identidade."""

import sqlite3
from pathlib import Path
from typing import Any

from contracts.eventos import StatusUsuario, UsuarioStatusAlterado
from shared.db import transaction


def consumir_usuario_status_alterado(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> None:
    """Atualiza o status sem permitir que eventos antigos sobrescrevam novos."""
    evento = UsuarioStatusAlterado.model_validate(payload)

    conn.execute(
        """
        INSERT INTO investidor_status (
            investidor_id, status, alterado_em
        )
        VALUES (?, ?, ?)
        ON CONFLICT(investidor_id) DO UPDATE SET
            status = excluded.status,
            alterado_em = excluded.alterado_em
        WHERE excluded.alterado_em > investidor_status.alterado_em
        """,
        (
            evento.usuario_id,
            evento.status_novo.value,
            evento.alterado_em.isoformat(),
        ),
    )


def investidor_esta_bloqueado(
    investidor_id: str,
    data_dir: str | Path = "data",
) -> bool:
    """Consulta o último status conhecido do investidor."""

    def consultar(conn: sqlite3.Connection) -> bool:
        registro = conn.execute(
            """
            SELECT status
            FROM investidor_status
            WHERE investidor_id = ?
            """,
            (investidor_id,),
        ).fetchone()

        return registro is not None and registro[0] == StatusUsuario.BLOQUEADO.value

    return transaction(consultar, "aportes", data_dir)
