"""Persistência do agregado Campanha no SQLite."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from campanhas.domain import (
    Campanha,
    ConcorrenciaOtimistaError,
    Meta,
    Prazo,
    StatusCampanha,
    TransicaoInvalidaError,
)
from shared.db import migrate, open_db
from shared.messaging_schema import install_messaging_schema

SERVICE = "campanhas"
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def inicializar_banco(data_dir: str | Path = "data") -> None:
    """Aplica migrations do serviço e instala tabelas de outbox e idempotência."""
    migrate(SERVICE, MIGRATIONS_DIR, data_dir)
    install_messaging_schema(SERVICE, data_dir)


def obter_conexao_leitura(data_dir: str | Path = "data") -> sqlite3.Connection:
    """Abre uma conexão de leitura dedicada que simula uma réplica (CQRS leve)."""
    return open_db(SERVICE, data_dir)


def executar_leitura[T](
    fn: Callable[[sqlite3.Connection], T],
    data_dir: str | Path = "data",
) -> T:
    """Executa consulta de leitura na conexão que simula a réplica."""
    with closing(obter_conexao_leitura(data_dir)) as conn:
        return fn(conn)


def _row_to_campanha(row: sqlite3.Row | tuple[Any, ...]) -> Campanha:
    """Converte linha do banco para a entidade Campanha."""
    prazo_inicio = datetime.fromisoformat(row[5])
    if prazo_inicio.tzinfo is None:
        prazo_inicio = prazo_inicio.replace(tzinfo=UTC)
    prazo_fim = datetime.fromisoformat(row[6])
    if prazo_fim.tzinfo is None:
        prazo_fim = prazo_fim.replace(tzinfo=UTC)
    criado_em = datetime.fromisoformat(row[11])
    if criado_em.tzinfo is None:
        criado_em = criado_em.replace(tzinfo=UTC)
    atualizado_em = datetime.fromisoformat(row[12])
    if atualizado_em.tzinfo is None:
        atualizado_em = atualizado_em.replace(tzinfo=UTC)

    return Campanha(
        id=str(row[0]),
        empreendedor_id=str(row[1]),
        titulo=str(row[2]),
        descricao=str(row[3]),
        meta=Meta(int(row[4])),
        prazo=Prazo(prazo_inicio, prazo_fim),
        status=StatusCampanha(str(row[7])),
        valor_arrecadado=int(row[8]),
        motivo_reprovacao=str(row[9]) if row[9] is not None else None,
        versao=int(row[10]),
        criado_em=criado_em,
        atualizado_em=atualizado_em,
    )


def salvar_nova_campanha(conn: sqlite3.Connection, campanha: Campanha) -> None:
    """Insere nova campanha no banco."""
    conn.execute(
        """
        INSERT INTO campanhas (
            id, empreendedor_id, titulo, descricao, meta,
            prazo_inicio, prazo_fim, status, valor_arrecadado,
            motivo_reprovacao, versao, criado_em, atualizado_em
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            campanha.id,
            campanha.empreendedor_id,
            campanha.titulo,
            campanha.descricao,
            campanha.meta.centavos,
            campanha.prazo.inicio.isoformat(),
            campanha.prazo.fim.isoformat(),
            campanha.status.value,
            campanha.valor_arrecadado,
            campanha.motivo_reprovacao,
            campanha.versao,
            campanha.criado_em.isoformat(),
            campanha.atualizado_em.isoformat(),
        ),
    )


def obter_campanha_por_id(conn: sqlite3.Connection, campanha_id: str) -> Campanha | None:
    """Busca campanha pelo ID."""
    row = conn.execute(
        """
        SELECT
            id, empreendedor_id, titulo, descricao, meta,
            prazo_inicio, prazo_fim, status, valor_arrecadado,
            motivo_reprovacao, versao, criado_em, atualizado_em
        FROM campanhas
        WHERE id = ?
        """,
        (campanha_id,),
    ).fetchone()

    if row is None:
        return None
    return _row_to_campanha(row)


def atualizar_campanha_rascunho(
    conn: sqlite3.Connection,
    campanha: Campanha,
    versao_esperada: int,
) -> None:
    """Atualiza dados de uma campanha em rascunho com concorrência otimista."""
    cursor = conn.execute(
        """
        UPDATE campanhas
        SET
            titulo = ?,
            descricao = ?,
            meta = ?,
            prazo_inicio = ?,
            prazo_fim = ?,
            versao = versao + 1,
            atualizado_em = ?
        WHERE id = ? AND versao = ? AND status = 'RASCUNHO'
        """,
        (
            campanha.titulo,
            campanha.descricao,
            campanha.meta.centavos,
            campanha.prazo.inicio.isoformat(),
            campanha.prazo.fim.isoformat(),
            campanha.atualizado_em.isoformat(),
            campanha.id,
            versao_esperada,
        ),
    )

    if cursor.rowcount == 0:
        atual = obter_campanha_por_id(conn, campanha.id)
        if atual is None:
            raise KeyError(f"Campanha '{campanha.id}' não encontrada.")
        if atual.status != StatusCampanha.RASCUNHO:
            raise TransicaoInvalidaError(
                f"Campanha está com status '{atual.status.value}'; "
                "apenas campanhas em RASCUNHO podem ser editadas."
            )
        if atual.versao != versao_esperada:
            raise ConcorrenciaOtimistaError(
                f"Conflito de concorrência: versão esperada {versao_esperada}, "
                f"mas versão atual é {atual.versao}."
            )
        raise RuntimeError("Não foi possível atualizar a campanha.")


def atualizar_campanha(
    conn: sqlite3.Connection,
    campanha: Campanha,
    versao_esperada: int,
) -> None:
    """Atualiza o estado de uma campanha usando controle de concorrência otimista."""
    cursor = conn.execute(
        """
        UPDATE campanhas
        SET
            titulo = ?,
            descricao = ?,
            meta = ?,
            prazo_inicio = ?,
            prazo_fim = ?,
            status = ?,
            valor_arrecadado = ?,
            motivo_reprovacao = ?,
            versao = versao + 1,
            atualizado_em = ?
        WHERE id = ? AND versao = ?
        """,
        (
            campanha.titulo,
            campanha.descricao,
            campanha.meta.centavos,
            campanha.prazo.inicio.isoformat(),
            campanha.prazo.fim.isoformat(),
            campanha.status.value,
            campanha.valor_arrecadado,
            campanha.motivo_reprovacao,
            campanha.atualizado_em.isoformat(),
            campanha.id,
            versao_esperada,
        ),
    )

    if cursor.rowcount == 0:
        atual = obter_campanha_por_id(conn, campanha.id)
        if atual is None:
            raise KeyError(f"Campanha '{campanha.id}' não encontrada.")
        if atual.versao != versao_esperada:
            raise ConcorrenciaOtimistaError(
                f"Conflito de concorrência: versão esperada {versao_esperada}, "
                f"mas versão atual é {atual.versao}."
            )
        raise RuntimeError("Não foi possível atualizar a campanha.")


def listar_campanhas(
    conn: sqlite3.Connection,
    status: StatusCampanha | None = None,
    limite: int = 20,
    offset: int = 0,
) -> list[Campanha]:
    """Lista campanhas cadastradas com paginação, opcionalmente filtrando por status."""
    query = """
        SELECT
            id, empreendedor_id, titulo, descricao, meta,
            prazo_inicio, prazo_fim, status, valor_arrecadado,
            motivo_reprovacao, versao, criado_em, atualizado_em
        FROM campanhas
    """
    params: list[Any] = []
    if status is not None:
        query += " WHERE status = ?"
        params.append(status.value)
    query += " ORDER BY criado_em DESC LIMIT ? OFFSET ?"
    params.extend([limite, offset])

    cursor = conn.execute(query, tuple(params))
    return [_row_to_campanha(row) for row in cursor.fetchall()]
