"""Testes do módulo KYC e da idempotência por usuarioId."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from contracts.eventos import Perfil
from identidade.contas.servico import cadastrar_usuario
from identidade.kyc.dominio import StatusVerificacao
from identidade.kyc.repositorio import (
    buscar_verificacao_pendente,
    listar_verificacoes_usuario,
)
from identidade.kyc.servico import (
    NovaVerificacaoNaoPermitidaErro,
    processar_usuario_cadastrado,
    solicitar_nova_verificacao,
)
from shared.db import migrate, transaction
from shared.messaging_schema import install_messaging_schema

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    migrate("identidade", MIGRATIONS_DIR, tmp_path)
    install_messaging_schema("identidade", tmp_path)
    return tmp_path


def criar_usuario(data_dir: Path) -> str:
    usuario = cadastrar_usuario(
        nome="Usuário KYC",
        email_str=f"kyc-{uuid4()}@exemplo.com",
        senha_plana="SenhaSegura123!",
        perfil=Perfil.INVESTIDOR,
        data_dir=data_dir,
    )
    return usuario.id


def test_usuario_cadastrado_cria_verificacao_pendente(data_dir: Path) -> None:
    usuario_id = criar_usuario(data_dir)

    criado = transaction(
        lambda conn: processar_usuario_cadastrado(conn, usuario_id),
        "identidade",
        data_dir,
    )

    verificacao = transaction(
        lambda conn: buscar_verificacao_pendente(conn, usuario_id),
        "identidade",
        data_dir,
    )

    assert criado is True
    assert verificacao is not None
    assert verificacao.usuario_id == usuario_id
    assert verificacao.status == StatusVerificacao.PENDENTE


def test_reentrega_usuario_cadastrado_nao_duplica(data_dir: Path) -> None:
    usuario_id = criar_usuario(data_dir)

    primeira = transaction(
        lambda conn: processar_usuario_cadastrado(conn, usuario_id),
        "identidade",
        data_dir,
    )
    segunda = transaction(
        lambda conn: processar_usuario_cadastrado(conn, usuario_id),
        "identidade",
        data_dir,
    )

    historico = transaction(
        lambda conn: listar_verificacoes_usuario(conn, usuario_id),
        "identidade",
        data_dir,
    )

    assert primeira is True
    assert segunda is False
    assert len(historico) == 1


def test_nova_verificacao_com_pendente_e_rejeitada(data_dir: Path) -> None:
    usuario_id = criar_usuario(data_dir)

    transaction(
        lambda conn: processar_usuario_cadastrado(conn, usuario_id),
        "identidade",
        data_dir,
    )

    with pytest.raises(NovaVerificacaoNaoPermitidaErro):
        solicitar_nova_verificacao(usuario_id, data_dir)


def test_reprovacao_permite_nova_verificacao_e_preserva_historico(
    data_dir: Path,
) -> None:
    usuario_id = criar_usuario(data_dir)

    transaction(
        lambda conn: processar_usuario_cadastrado(conn, usuario_id),
        "identidade",
        data_dir,
    )

    def reprovar(conn: sqlite3.Connection) -> None:
        verificacao = buscar_verificacao_pendente(conn, usuario_id)
        assert verificacao is not None
        reprovada = verificacao.reprovar()

        assert reprovada.atualizado_em is not None

        conn.execute(
            """
            UPDATE kyc_verificacoes
            SET status = ?, atualizado_em = ?
            WHERE id = ?
            """,
            (
                reprovada.status.value,
                reprovada.atualizado_em.isoformat(),
                reprovada.id,
            ),
        )

    transaction(reprovar, "identidade", data_dir)

    nova = solicitar_nova_verificacao(usuario_id, data_dir)

    historico = transaction(
        lambda conn: listar_verificacoes_usuario(conn, usuario_id),
        "identidade",
        data_dir,
    )

    assert nova.status == StatusVerificacao.PENDENTE
    assert len(historico) == 2
    assert {item.status for item in historico} == {
        StatusVerificacao.REPROVADA,
        StatusVerificacao.PENDENTE,
    }


def test_reentrega_apos_reprovacao_nao_cria_verificacao_extra(
    data_dir: Path,
) -> None:
    usuario_id = criar_usuario(data_dir)

    transaction(
        lambda conn: processar_usuario_cadastrado(conn, usuario_id),
        "identidade",
        data_dir,
    )

    def reprovar(conn: sqlite3.Connection) -> None:
        verificacao = buscar_verificacao_pendente(conn, usuario_id)
        assert verificacao is not None
        reprovada = verificacao.reprovar()
        conn.execute(
            "UPDATE kyc_verificacoes SET status = ? WHERE id = ?",
            (reprovada.status.value, reprovada.id),
        )

    transaction(reprovar, "identidade", data_dir)

    reentrega = transaction(
        lambda conn: processar_usuario_cadastrado(conn, usuario_id),
        "identidade",
        data_dir,
    )

    historico = transaction(
        lambda conn: listar_verificacoes_usuario(conn, usuario_id),
        "identidade",
        data_dir,
    )

    assert reentrega is False
    assert len(historico) == 1
    assert historico[0].status == StatusVerificacao.REPROVADA
