"""Casos de uso do módulo KYC."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from identidade.contas.repositorio import buscar_usuario_por_id
from identidade.kyc.dominio import StatusVerificacao, VerificacaoIdentidade
from identidade.kyc.provider import KycProvider
from identidade.kyc.repositorio import (
    buscar_verificacao_pendente,
    listar_verificacoes_usuario,
    salvar_verificacao,
)
from shared.db import transaction


class UsuarioKycNaoEncontradoErro(ValueError):
    """Usuário não encontrado."""


class NovaVerificacaoNaoPermitidaErro(ValueError):
    """Não é permitido iniciar outra verificação."""


def _criar_verificacao(
    conn: sqlite3.Connection,
    usuario_id: str,
) -> VerificacaoIdentidade:
    verificacao = VerificacaoIdentidade.criar_pendente(
        verificacao_id=str(uuid4()),
        usuario_id=usuario_id,
    )
    salvar_verificacao(conn, verificacao)
    return verificacao


def processar_usuario_cadastrado(
    conn: sqlite3.Connection,
    usuario_id: str,
) -> bool:
    """Inicializa o KYC uma única vez por usuário.

    Executado na transação do consumidor de eventos.
    """
    if buscar_usuario_por_id(conn, usuario_id) is None:
        raise UsuarioKycNaoEncontradoErro("Usuário não encontrado")

    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO kyc_usuarios_inicializados (usuario_id)
        VALUES (?)
        """,
        (usuario_id,),
    )

    if cursor.rowcount == 0:
        return False

    _criar_verificacao(conn, usuario_id)
    return True


def solicitar_nova_verificacao(
    usuario_id: str,
    data_dir: str | Path = "data",
) -> VerificacaoIdentidade:
    """Cria uma nova verificação após reprovação ou expiração."""

    def operacao(conn: sqlite3.Connection) -> VerificacaoIdentidade:
        if buscar_usuario_por_id(conn, usuario_id) is None:
            raise UsuarioKycNaoEncontradoErro("Usuário não encontrado")

        if buscar_verificacao_pendente(conn, usuario_id) is not None:
            raise NovaVerificacaoNaoPermitidaErro("O usuário já possui uma verificação PENDENTE")

        historico = listar_verificacoes_usuario(conn, usuario_id)

        if not historico:
            raise NovaVerificacaoNaoPermitidaErro("A verificação inicial ainda não foi criada")

        if any(verificacao.status == StatusVerificacao.APROVADA for verificacao in historico):
            raise NovaVerificacaoNaoPermitidaErro("O usuário já possui uma verificação APROVADA")

        if historico[0].status not in (
            StatusVerificacao.REPROVADA,
            StatusVerificacao.EXPIRADA,
        ):
            raise NovaVerificacaoNaoPermitidaErro(
                "A verificação anterior deve estar REPROVADA ou EXPIRADA"
            )

        return _criar_verificacao(conn, usuario_id)

    return transaction(operacao, "identidade", data_dir)


class VerificacaoKycNaoEncontradaErro(ValueError):
    """O usuário não possui uma verificação KYC pendente."""


def registrar_documento_kyc(
    usuario_id: str,
    *,
    tipo: str,
    numero: str,
    data_dir: str | Path = "data",
) -> VerificacaoIdentidade:
    """Registra somente o hash do documento na verificação pendente."""
    from identidade.kyc.repositorio import atualizar_verificacao
    from identidade.kyc.seguranca import gerar_hash_documento

    documento_hash = gerar_hash_documento(tipo, numero)

    def operacao(conn: sqlite3.Connection) -> VerificacaoIdentidade:
        verificacao = buscar_verificacao_pendente(conn, usuario_id)

        if verificacao is None:
            raise VerificacaoKycNaoEncontradaErro("Nenhuma verificação KYC pendente encontrada")

        atualizada = verificacao.registrar_documento(
            tipo=tipo.strip().upper(),
            documento_hash=documento_hash,
        )

        if not atualizar_verificacao(conn, atualizada):
            raise VerificacaoKycNaoEncontradaErro(
                "Não foi possível atualizar a verificação pendente"
            )

        return atualizada

    return transaction(operacao, "identidade", data_dir)


def verificar_documento_com_provider(
    usuario_id: str,
    *,
    tipo: str,
    numero: str,
    provider: KycProvider,
    data_dir: str | Path = "data",
) -> VerificacaoIdentidade:
    """Verifica com provedor e persiste decisão atomicamente."""

    from identidade.kyc.decisao import decidir_documento_automaticamente
    from identidade.kyc.seguranca import gerar_hash_documento

    resultado = provider.verificar(tipo=tipo, numero=numero)

    if resultado.status not in (
        StatusVerificacao.APROVADA,
        StatusVerificacao.REPROVADA,
    ):
        raise ValueError("O provedor deve retornar APROVADA ou REPROVADA")

    documento_hash = gerar_hash_documento(tipo, numero)

    return decidir_documento_automaticamente(
        usuario_id,
        status=resultado.status,
        tipo=tipo,
        documento_hash=documento_hash,
        data_dir=data_dir,
    )


def consultar_status_kyc(
    usuario_id: str,
    data_dir: str | Path = "data",
) -> VerificacaoIdentidade | None:
    """Retorna a verificação mais recente do usuário."""

    def operacao(conn: sqlite3.Connection) -> VerificacaoIdentidade | None:
        verificacoes = listar_verificacoes_usuario(conn, usuario_id)
        return verificacoes[0] if verificacoes else None

    return transaction(operacao, "identidade", data_dir)
