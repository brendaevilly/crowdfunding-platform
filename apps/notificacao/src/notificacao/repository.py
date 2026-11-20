"""Persistência de notificações no SQLite."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from notificacao.domain import Notificacao, StatusEnvio
from shared.db import migrate
from shared.messaging_schema import install_messaging_schema

SERVICE = "notificacao"
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def inicializar_banco(data_dir: str | Path = "data") -> None:
    """Aplica migrations do serviço e instala tabelas de mensageria."""
    migrate(SERVICE, MIGRATIONS_DIR, data_dir)
    install_messaging_schema(SERVICE, data_dir)


def _row_to_notificacao(row: sqlite3.Row | tuple[Any, ...]) -> Notificacao:
    """Converte registro do banco na entidade Notificacao."""
    criado_em = datetime.fromisoformat(row[8]) if row[8] else None
    if criado_em and criado_em.tzinfo is None:
        criado_em = criado_em.replace(tzinfo=UTC)

    enviado_em = datetime.fromisoformat(row[9]) if row[9] else None
    if enviado_em and enviado_em.tzinfo is None:
        enviado_em = enviado_em.replace(tzinfo=UTC)

    return Notificacao(
        id=str(row[0]),
        usuario_id=str(row[1]),
        evento_origem_id=str(row[2]),
        tipo_evento=str(row[3]),
        titulo=str(row[4]),
        mensagem=str(row[5]),
        status_envio=StatusEnvio(str(row[6])),
        lida=bool(row[7]),
        criado_em=criado_em,
        enviado_em=enviado_em,
    )


def salvar_notificacao(conn: sqlite3.Connection, notificacao: Notificacao) -> bool:
    """Salva notificação de forma idempotente.

    Retorna True se foi inserida, ou False se já existia para o par (usuario_id, evento_origem_id).
    """
    criado_iso = (
        notificacao.criado_em.isoformat()
        if notificacao.criado_em
        else datetime.now(UTC).isoformat()
    )
    enviado_iso = notificacao.enviado_em.isoformat() if notificacao.enviado_em else None

    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO notificacao (
            id, usuario_id, evento_origem_id, tipo_evento,
            titulo, mensagem, status_envio, lida,
            criado_em, enviado_em
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            notificacao.id,
            notificacao.usuario_id,
            notificacao.evento_origem_id,
            notificacao.tipo_evento,
            notificacao.titulo,
            notificacao.mensagem,
            notificacao.status_envio.value,
            1 if notificacao.lida else 0,
            criado_iso,
            enviado_iso,
        ),
    )
    return cursor.rowcount > 0


def listar_notificacoes_usuario(
    conn: sqlite3.Connection,
    usuario_id: str,
) -> list[Notificacao]:
    """Lista notificações do usuário ordenadas da mais recente para a mais antiga."""
    rows = conn.execute(
        """
        SELECT
            id, usuario_id, evento_origem_id, tipo_evento,
            titulo, mensagem, status_envio, lida,
            criado_em, enviado_em
        FROM notificacao
        WHERE usuario_id = ?
        ORDER BY criado_em DESC
        """,
        (usuario_id,),
    ).fetchall()

    return [_row_to_notificacao(row) for row in rows]


def obter_notificacao_por_id(
    conn: sqlite3.Connection,
    notificacao_id: str,
) -> Notificacao | None:
    """Busca uma notificação pelo seu identificador primário."""
    row = conn.execute(
        """
        SELECT
            id, usuario_id, evento_origem_id, tipo_evento,
            titulo, mensagem, status_envio, lida,
            criado_em, enviado_em
        FROM notificacao
        WHERE id = ?
        """,
        (notificacao_id,),
    ).fetchone()

    if row is None:
        return None
    return _row_to_notificacao(row)


def marcar_notificacao_como_lida(
    conn: sqlite3.Connection,
    notificacao_id: str,
    usuario_id: str,
) -> bool:
    """Marca a notificação como lida para o usuário informado."""
    cursor = conn.execute(
        """
        UPDATE notificacao
        SET lida = 1
        WHERE id = ? AND usuario_id = ?
        """,
        (notificacao_id, usuario_id),
    )
    return cursor.rowcount > 0


def expirar_notificacoes_antigas(
    conn: sqlite3.Connection,
    dias_ttl: int,
) -> int:
    """Remove notificações criadas há mais de dias_ttl dias.

    Retorna a quantidade de registros expirados removidos.
    """
    if dias_ttl <= 0:
        raise ValueError("dias_ttl deve ser maior que zero")

    limite = datetime.now(UTC) - timedelta(days=dias_ttl)
    cursor = conn.execute(
        """
        DELETE FROM notificacao
        WHERE criado_em < ?
        """,
        (limite.isoformat(),),
    )
    return cursor.rowcount
