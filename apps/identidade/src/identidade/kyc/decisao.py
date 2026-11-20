"""Decisão de verificações KYC e publicação transacional de eventos."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from contracts.eventos import IdentidadeVerificada
from contracts.topicos import IDENTIDADE_VERIFICADA
from identidade.kyc.dominio import StatusVerificacao, VerificacaoIdentidade
from identidade.kyc.repositorio import (
    atualizar_verificacao,
    buscar_verificacao_pendente,
)
from shared.correlation import get_correlation_id
from shared.db import transaction
from shared.outbox import OutboxEvent, add


class DecisaoKycNaoPermitidaErro(ValueError):
    """A verificação não permite uma nova decisão."""


def _decidir_na_transacao(
    conn: sqlite3.Connection,
    usuario_id: str,
    *,
    status: StatusVerificacao,
    tipo: str | None = None,
    documento_hash: str | None = None,
) -> VerificacaoIdentidade:
    """Registra documento opcional e decide na mesma transação."""

    if status not in (
        StatusVerificacao.APROVADA,
        StatusVerificacao.REPROVADA,
    ):
        raise DecisaoKycNaoPermitidaErro("A decisão deve ser APROVADA ou REPROVADA")

    verificacao = buscar_verificacao_pendente(conn, usuario_id)

    if verificacao is None:
        from identidade.kyc.repositorio import listar_verificacoes_usuario
        from identidade.kyc.servico import _criar_verificacao, processar_usuario_cadastrado

        processar_usuario_cadastrado(conn, usuario_id)
        verificacao = buscar_verificacao_pendente(conn, usuario_id)

        if verificacao is None:
            historico = listar_verificacoes_usuario(conn, usuario_id)
            if historico and historico[0].status in (
                StatusVerificacao.REPROVADA,
                StatusVerificacao.EXPIRADA,
            ):
                verificacao = _criar_verificacao(conn, usuario_id)

    if verificacao is None:
        raise DecisaoKycNaoPermitidaErro("Nenhuma verificação KYC PENDENTE encontrada")

    if tipo is not None and documento_hash is not None:
        verificacao = verificacao.registrar_documento(
            tipo=tipo.strip().upper(),
            documento_hash=documento_hash,
        )

    if verificacao.documento_hash is None:
        raise DecisaoKycNaoPermitidaErro("É necessário registrar um documento antes da decisão")

    if status == StatusVerificacao.APROVADA:
        atualizada = verificacao.aprovar()
    else:
        atualizada = verificacao.reprovar()

    if not atualizar_verificacao(conn, atualizada):
        raise DecisaoKycNaoPermitidaErro("Não foi possível atualizar a verificação KYC")

    if atualizada.status == StatusVerificacao.APROVADA:
        if atualizada.atualizado_em is None:
            raise DecisaoKycNaoPermitidaErro("Data da verificação não encontrada")

        contrato = IdentidadeVerificada(
            usuario_id=usuario_id,
            verificada_em=atualizada.atualizado_em,
        )

        add(
            conn,
            OutboxEvent(
                agregado_id=usuario_id,
                tipo_evento=IDENTIDADE_VERIFICADA,
                payload=contrato.model_dump(
                    by_alias=True,
                    mode="json",
                ),
                correlation_id=get_correlation_id() or str(uuid4()),
            ),
        )

    return atualizada


def decidir_verificacao_kyc(
    usuario_id: str,
    *,
    status: StatusVerificacao,
    data_dir: str | Path = "data",
) -> VerificacaoIdentidade:
    """Decisão manual sobre documento previamente registrado."""

    return transaction(
        lambda conn: _decidir_na_transacao(
            conn,
            usuario_id,
            status=status,
        ),
        "identidade",
        data_dir,
    )


def decidir_documento_automaticamente(
    usuario_id: str,
    *,
    status: StatusVerificacao,
    tipo: str,
    documento_hash: str,
    data_dir: str | Path = "data",
) -> VerificacaoIdentidade:
    """Registra o hash e decide em uma única transação."""

    return transaction(
        lambda conn: _decidir_na_transacao(
            conn,
            usuario_id,
            status=status,
            tipo=tipo,
            documento_hash=documento_hash,
        ),
        "identidade",
        data_dir,
    )
