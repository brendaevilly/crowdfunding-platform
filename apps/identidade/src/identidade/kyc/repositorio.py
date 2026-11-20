"""Persistência do agregado VerificacaoIdentidade em SQLite."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from identidade.kyc.dominio import StatusVerificacao, VerificacaoIdentidade


class VerificacaoPendenteExistenteErro(ValueError):
    """O usuário já possui uma verificação pendente."""


def _parse_datetime(valor: str) -> datetime:
    """Converte datas armazenadas no SQLite."""
    data = datetime.fromisoformat(valor)

    if data.tzinfo is None:
        data = data.replace(tzinfo=UTC)

    return data


def _linha_para_verificacao(linha: tuple[Any, ...]) -> VerificacaoIdentidade:
    """Converte um registro SQLite para o agregado KYC."""
    return VerificacaoIdentidade(
        id=str(linha[0]),
        usuario_id=str(linha[1]),
        status=StatusVerificacao(str(linha[2])),
        documento_tipo=str(linha[3]) if linha[3] is not None else None,
        documento_hash=str(linha[4]) if linha[4] is not None else None,
        criado_em=_parse_datetime(str(linha[5])),
        atualizado_em=_parse_datetime(str(linha[6])),
    )


def salvar_verificacao(
    conn: sqlite3.Connection,
    verificacao: VerificacaoIdentidade,
) -> None:
    """Salva uma nova verificação, respeitando o índice único parcial."""
    try:
        conn.execute(
            """
            INSERT INTO kyc_verificacoes (
                id,
                usuario_id,
                status,
                documento_tipo,
                documento_hash,
                criado_em,
                atualizado_em
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                verificacao.id,
                verificacao.usuario_id,
                verificacao.status.value,
                verificacao.documento_tipo,
                verificacao.documento_hash,
                verificacao.criado_em.isoformat()
                if verificacao.criado_em is not None
                else datetime.now(UTC).isoformat(),
                verificacao.atualizado_em.isoformat()
                if verificacao.atualizado_em is not None
                else datetime.now(UTC).isoformat(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        if "UNIQUE constraint failed: kyc_verificacoes.usuario_id" in str(exc):
            raise VerificacaoPendenteExistenteErro(
                "O usuário já possui uma verificação PENDENTE"
            ) from exc
        raise


def buscar_verificacao_por_id(
    conn: sqlite3.Connection,
    verificacao_id: str,
) -> VerificacaoIdentidade | None:
    """Busca uma verificação pelo identificador."""
    linha = conn.execute(
        """
        SELECT id, usuario_id, status, documento_tipo, documento_hash,
               criado_em, atualizado_em
        FROM kyc_verificacoes
        WHERE id = ?
        """,
        (verificacao_id,),
    ).fetchone()

    if linha is None:
        return None

    return _linha_para_verificacao(linha)


def buscar_verificacao_pendente(
    conn: sqlite3.Connection,
    usuario_id: str,
) -> VerificacaoIdentidade | None:
    """Busca a verificação PENDENTE do usuário."""
    linha = conn.execute(
        """
        SELECT id, usuario_id, status, documento_tipo, documento_hash,
               criado_em, atualizado_em
        FROM kyc_verificacoes
        WHERE usuario_id = ?
          AND status = 'PENDENTE'
        LIMIT 1
        """,
        (usuario_id,),
    ).fetchone()

    if linha is None:
        return None

    return _linha_para_verificacao(linha)


def listar_verificacoes_usuario(
    conn: sqlite3.Connection,
    usuario_id: str,
) -> list[VerificacaoIdentidade]:
    """Retorna o histórico de verificações, da mais recente à mais antiga."""
    linhas = conn.execute(
        """
        SELECT id, usuario_id, status, documento_tipo, documento_hash,
               criado_em, atualizado_em
        FROM kyc_verificacoes
        WHERE usuario_id = ?
        ORDER BY criado_em DESC, id DESC
        """,
        (usuario_id,),
    ).fetchall()

    return [_linha_para_verificacao(linha) for linha in linhas]


def atualizar_verificacao(
    conn: sqlite3.Connection,
    verificacao: VerificacaoIdentidade,
) -> bool:
    """Atualiza uma verificação ainda pendente.

    A trigger do banco também protege verificações APROVADAS.
    """
    cursor = conn.execute(
        """
        UPDATE kyc_verificacoes
        SET status = ?,
            documento_tipo = ?,
            documento_hash = ?,
            atualizado_em = ?
        WHERE id = ?
          AND status = 'PENDENTE'
        """,
        (
            verificacao.status.value,
            verificacao.documento_tipo,
            verificacao.documento_hash,
            verificacao.atualizado_em.isoformat()
            if verificacao.atualizado_em is not None
            else datetime.now(UTC).isoformat(),
            verificacao.id,
        ),
    )

    return cursor.rowcount == 1


def listar_verificacoes_pendentes(
    conn: sqlite3.Connection,
) -> list[VerificacaoIdentidade]:
    """Lista todas as verificações pendentes, da mais antiga à mais recente."""
    linhas = conn.execute(
        """
        SELECT id, usuario_id, status, documento_tipo, documento_hash,
               criado_em, atualizado_em
        FROM kyc_verificacoes
        WHERE status = 'PENDENTE'
        ORDER BY criado_em ASC, id ASC
        """
    ).fetchall()

    return [_linha_para_verificacao(linha) for linha in linhas]
