"""Persistência do bounded context Contas via SQLite."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from contracts.eventos import Perfil
from identidade.contas.dominio import Email, StatusUsuario, Usuario


def _parse_datetime(val: str) -> datetime:
    try:
        dt = datetime.fromisoformat(val)
    except ValueError:
        dt = datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _linha_para_usuario(linha: tuple[Any, ...]) -> Usuario:
    return Usuario(
        id=str(linha[0]),
        nome=str(linha[1]),
        email=Email(str(linha[2])),
        senha_hash=str(linha[3]),
        perfil=Perfil(str(linha[4])),
        status=StatusUsuario(str(linha[5])),
        criado_em=_parse_datetime(str(linha[6])),
        atualizado_em=_parse_datetime(str(linha[7])),
    )


def salvar_usuario(conn: sqlite3.Connection, usuario: Usuario) -> None:
    """Insere um novo usuário na tabela contas_usuarios."""
    conn.execute(
        """
        INSERT INTO contas_usuarios (
            id,
            nome,
            email,
            senha_hash,
            perfil,
            status,
            criado_em,
            atualizado_em
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            usuario.id,
            usuario.nome,
            usuario.email.valor,
            usuario.senha_hash,
            usuario.perfil.value,
            usuario.status.value,
            usuario.criado_em.isoformat(),
            usuario.atualizado_em.isoformat(),
        ),
    )


def buscar_usuario_por_id(conn: sqlite3.Connection, usuario_id: str) -> Usuario | None:
    """Busca usuário pelo seu id."""
    linha = conn.execute(
        """
        SELECT id, nome, email, senha_hash, perfil, status, criado_em, atualizado_em
        FROM contas_usuarios
        WHERE id = ?
        """,
        (usuario_id,),
    ).fetchone()
    if linha is None:
        return None
    return _linha_para_usuario(linha)


def buscar_usuario_por_email(conn: sqlite3.Connection, email: str) -> Usuario | None:
    """Busca usuário pelo seu e-mail normalizado."""
    linha = conn.execute(
        """
        SELECT id, nome, email, senha_hash, perfil, status, criado_em, atualizado_em
        FROM contas_usuarios
        WHERE email = ?
        """,
        (email.strip().lower(),),
    ).fetchone()
    if linha is None:
        return None
    return _linha_para_usuario(linha)


def atualizar_status_usuario(
    conn: sqlite3.Connection,
    usuario_id: str,
    novo_status: StatusUsuario,
    atualizado_em: datetime,
) -> bool:
    """Atualiza o status e atualizado_em do usuário."""
    cursor = conn.execute(
        """
        UPDATE contas_usuarios
        SET status = ?,
            atualizado_em = ?
        WHERE id = ?
        """,
        (
            novo_status.value,
            atualizado_em.isoformat(),
            usuario_id,
        ),
    )
    return cursor.rowcount == 1
