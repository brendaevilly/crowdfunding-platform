"""Consumo idempotente de eventos de Identidade e cache local de usuários."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from contracts.eventos import Perfil, StatusUsuario, UsuarioCadastrado, UsuarioStatusAlterado
from shared.db import transaction


def consumir_usuario_cadastrado(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> None:
    """Registra usuário na projeção local."""
    evento = UsuarioCadastrado.model_validate(payload)
    conn.execute(
        """
        INSERT INTO usuarios_cache (usuario_id, perfil, status, alterado_em)
        VALUES (?, ?, 'ATIVO', ?)
        ON CONFLICT(usuario_id) DO UPDATE SET
            perfil = excluded.perfil
        WHERE excluded.alterado_em >= usuarios_cache.alterado_em
        """,
        (
            evento.usuario_id,
            evento.perfil.value,
            evento.cadastrado_em.isoformat(),
        ),
    )


def consumir_usuario_status_alterado(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> None:
    """Atualiza o status do usuário na projeção local."""
    evento = UsuarioStatusAlterado.model_validate(payload)
    conn.execute(
        """
        INSERT INTO usuarios_cache (usuario_id, perfil, status, alterado_em)
        VALUES (?, 'DESCONHECIDO', ?, ?)
        ON CONFLICT(usuario_id) DO UPDATE SET
            status = excluded.status,
            alterado_em = excluded.alterado_em
        WHERE excluded.alterado_em >= usuarios_cache.alterado_em
        """,
        (
            evento.usuario_id,
            evento.status_novo.value,
            evento.alterado_em.isoformat(),
        ),
    )


def verificar_apto_a_criar_campanha(
    conn: sqlite3.Connection,
    usuario_id: str,
) -> tuple[bool, str | None]:
    """Verifica se o usuário é um EMPREENDEDOR com status ATIVO."""
    row = conn.execute(
        """
        SELECT perfil, status
        FROM usuarios_cache
        WHERE usuario_id = ?
        """,
        (usuario_id,),
    ).fetchone()

    if row is None:
        return False, "Usuário não encontrado na plataforma."

    perfil, status = row[0], row[1]
    if perfil != Perfil.EMPREENDEDOR.value:
        return (
            False,
            f"Usuário possui perfil '{perfil}', mas apenas EMPREENDEDOR pode criar campanhas.",
        )

    if status != StatusUsuario.ATIVO.value:
        return False, f"Empreendedor não está com status ATIVO (status atual: '{status}')."

    return True, None


def usuario_pode_criar_campanha(
    usuario_id: str,
    data_dir: str | Path = "data",
) -> tuple[bool, str | None]:
    """Helper transacional para consultar aptidão de usuário."""

    def operacao(conn: sqlite3.Connection) -> tuple[bool, str | None]:
        return verificar_apto_a_criar_campanha(conn, usuario_id)

    return transaction(operacao, "campanhas", data_dir)
