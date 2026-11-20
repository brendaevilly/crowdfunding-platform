"""Persistência do agregado Campanha no SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime
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
from shared.db import migrate
from shared.messaging_schema import install_messaging_schema

SERVICE = "campanhas"
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def inicializar_banco(data_dir: str | Path = "data") -> None:
    """Aplica migrations do serviço e instala tabelas de outbox e idempotência."""
    migrate(SERVICE, MIGRATIONS_DIR, data_dir)
    install_messaging_schema(SERVICE, data_dir)


def _row_to_campanha(row: sqlite3.Row | tuple[Any, ...]) -> Campanha:
    """Converte linha do banco para a entidade Campanha."""
    return Campanha(
        id=str(row[0]),
        empreendedor_id=str(row[1]),
        titulo=str(row[2]),
        descricao=str(row[3]),
        meta=Meta(int(row[4])),
        prazo=Prazo(datetime.fromisoformat(row[5]), datetime.fromisoformat(row[6])),
        status=StatusCampanha(str(row[7])),
        valor_arrecadado=int(row[8]),
        motivo_reprovacao=str(row[9]) if row[9] is not None else None,
        versao=int(row[10]),
        criado_em=datetime.fromisoformat(row[11]),
        atualizado_em=datetime.fromisoformat(row[12]),
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
