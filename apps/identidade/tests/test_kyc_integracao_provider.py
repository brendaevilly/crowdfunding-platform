"""Testes de integração do provedor KYC com SQLite e outbox."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from contracts.eventos import Perfil
from contracts.topicos import IDENTIDADE_VERIFICADA
from identidade.app import MIGRATIONS_DIR
from identidade.contas.servico import cadastrar_usuario
from identidade.kyc.decisao import (
    DecisaoKycNaoPermitidaErro,
    decidir_verificacao_kyc,
)
from identidade.kyc.dominio import StatusVerificacao
from identidade.kyc.mock_provider import MockKycProvider
from identidade.kyc.servico import (
    consultar_status_kyc,
    processar_usuario_cadastrado,
    registrar_documento_kyc,
    verificar_documento_com_provider,
)
from shared.db import migrate, open_db, transaction


@pytest.fixture
def ambiente(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, Path]:
    monkeypatch.setenv("KYC_HASH_SECRET", "segredo-testes-kyc")
    monkeypatch.setenv("JWT_SECRET", "segredo-testes-jwt")
    monkeypatch.setenv("IDENTIDADE_MESSAGING_ENABLED", "false")

    migrate("identidade", MIGRATIONS_DIR, tmp_path)
    from shared.messaging_schema import install_messaging_schema

    install_messaging_schema("identidade", tmp_path)

    usuario = cadastrar_usuario(
        nome="Teste de Integração KYC",
        email_str=f"kyc-{uuid4()}@exemplo.com",
        senha_plana="SenhaSegura123!",
        perfil=Perfil.INVESTIDOR,
        data_dir=tmp_path,
        auto_ativar=True,
    )

    transaction(
        lambda conn: processar_usuario_cadastrado(conn, usuario.id),
        "identidade",
        tmp_path,
    )

    return usuario.id, tmp_path


def contar_eventos(data_dir: Path) -> int:
    with open_db("identidade", data_dir) as conn:
        linha = conn.execute(
            "SELECT COUNT(*) FROM outbox_evento WHERE tipo_evento = ?",
            (IDENTIDADE_VERIFICADA,),
        ).fetchone()
        assert linha is not None
        return int(linha[0])


def test_aprovacao_automatica_publica_um_evento(
    ambiente: tuple[str, Path],
) -> None:
    usuario_id, data_dir = ambiente

    resultado = verificar_documento_com_provider(
        usuario_id,
        tipo="CPF",
        numero="12345678909",
        provider=MockKycProvider(),
        data_dir=data_dir,
    )

    assert resultado.status == StatusVerificacao.APROVADA
    assert contar_eventos(data_dir) == 1

    armazenada = consultar_status_kyc(usuario_id, data_dir)

    assert armazenada is not None
    assert armazenada.status == StatusVerificacao.APROVADA


def test_reprovacao_automatica_nao_publica_evento(
    ambiente: tuple[str, Path],
) -> None:
    usuario_id, data_dir = ambiente

    resultado = verificar_documento_com_provider(
        usuario_id,
        tipo="CPF",
        numero="12345678900",
        provider=MockKycProvider(),
        data_dir=data_dir,
    )

    assert resultado.status == StatusVerificacao.REPROVADA
    assert contar_eventos(data_dir) == 0


def test_decisao_repetida_nao_publica_evento_duplicado(
    ambiente: tuple[str, Path],
) -> None:
    usuario_id, data_dir = ambiente

    verificar_documento_com_provider(
        usuario_id,
        tipo="CPF",
        numero="12345678909",
        provider=MockKycProvider(),
        data_dir=data_dir,
    )

    with pytest.raises(DecisaoKycNaoPermitidaErro):
        decidir_verificacao_kyc(
            usuario_id,
            status=StatusVerificacao.APROVADA,
            data_dir=data_dir,
        )

    assert contar_eventos(data_dir) == 1


def test_decisao_manual_aprova_documento_pendente(
    ambiente: tuple[str, Path],
) -> None:
    usuario_id, data_dir = ambiente

    documento = registrar_documento_kyc(
        usuario_id,
        tipo="CPF",
        numero="12345678909",
        data_dir=data_dir,
    )

    assert documento.status == StatusVerificacao.PENDENTE

    resultado = decidir_verificacao_kyc(
        usuario_id,
        status=StatusVerificacao.APROVADA,
        data_dir=data_dir,
    )

    assert resultado.status == StatusVerificacao.APROVADA
    assert contar_eventos(data_dir) == 1


def test_falha_na_outbox_desfaz_aprovacao_e_documento(
    ambiente: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usuario_id, data_dir = ambiente

    def falhar_outbox(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("Falha simulada na outbox")

    monkeypatch.setattr(
        "identidade.kyc.decisao.add",
        falhar_outbox,
    )

    with pytest.raises(sqlite3.OperationalError):
        verificar_documento_com_provider(
            usuario_id,
            tipo="CPF",
            numero="12345678909",
            provider=MockKycProvider(),
            data_dir=data_dir,
        )

    armazenada = consultar_status_kyc(usuario_id, data_dir)

    assert armazenada is not None
    assert armazenada.status == StatusVerificacao.PENDENTE
    assert armazenada.documento_hash is None
    assert contar_eventos(data_dir) == 0
