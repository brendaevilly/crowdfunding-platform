"""Testes HTTP das rotas autenticadas do módulo KYC."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from contracts.eventos import Perfil
from identidade.app import criar_identidade_app
from identidade.contas.servico import cadastrar_usuario
from identidade.kyc.servico import processar_usuario_cadastrado
from shared.auth import emitir_token, segredo_do_ambiente
from shared.db import open_db, transaction


@pytest.fixture
def ambiente(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, Path]]:
    monkeypatch.setenv("IDENTIDADE_MESSAGING_ENABLED", "false")
    monkeypatch.setenv("KYC_HASH_SECRET", "chave-exclusiva-para-testes-kyc")
    monkeypatch.setenv("JWT_SECRET", "chave-exclusiva-para-testes-jwt")

    app = criar_identidade_app(tmp_path)

    with TestClient(app) as cliente:
        yield cliente, tmp_path


def criar_usuario_autenticado(data_dir: Path) -> tuple[str, str]:
    usuario = cadastrar_usuario(
        nome="Usuário de Teste KYC",
        email_str=f"teste-{uuid4()}@exemplo.com",
        senha_plana="SenhaSegura123!",
        perfil=Perfil.INVESTIDOR,
        data_dir=data_dir,
        auto_ativar=True,
    )

    transaction(
        lambda conn: processar_usuario_cadastrado(conn, usuario.id),
        "identidade",
        data_dir,
    )

    segredo, _ = segredo_do_ambiente()
    token = emitir_token(
        sub=usuario.id,
        perfil=usuario.perfil.value,
        segredo=segredo,
    )

    return usuario.id, token


def test_status_exige_autenticacao(ambiente: tuple[TestClient, Path]) -> None:
    cliente, _ = ambiente

    resposta = cliente.get("/kyc/status")

    assert resposta.status_code == 401


def test_documentos_exige_autenticacao(ambiente: tuple[TestClient, Path]) -> None:
    cliente, _ = ambiente

    resposta = cliente.post(
        "/kyc/documentos",
        json={"tipo": "CPF", "numero": "12345678909"},
    )

    assert resposta.status_code == 401


def test_status_retorna_verificacao_pendente(ambiente: tuple[TestClient, Path]) -> None:
    cliente, data_dir = ambiente
    _, token = criar_usuario_autenticado(data_dir)

    resposta = cliente.get(
        "/kyc/status",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "PENDENTE"
    assert resposta.json()["documentoTipo"] is None


def test_documento_armazenado_apenas_com_hash(ambiente: tuple[TestClient, Path]) -> None:
    cliente, data_dir = ambiente
    usuario_id, token = criar_usuario_autenticado(data_dir)
    numero = "12345678909"

    resposta = cliente.post(
        "/kyc/documentos",
        json={"tipo": "CPF", "numero": numero},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 200
    assert resposta.json()["documentoTipo"] == "CPF"
    assert numero not in resposta.text
    assert "documento_hash" not in resposta.json()

    with open_db("identidade", data_dir) as conn:
        registro = conn.execute(
            """
            SELECT documento_tipo, documento_hash
            FROM kyc_verificacoes
            WHERE usuario_id = ?
            """,
            (usuario_id,),
        ).fetchone()

    assert registro is not None
    assert registro[0] == "CPF"
    assert registro[1] != numero
    assert len(registro[1]) == 64


def test_usuario_nao_acessa_status_de_outro(ambiente: tuple[TestClient, Path]) -> None:
    cliente, data_dir = ambiente
    usuario_a, token_a = criar_usuario_autenticado(data_dir)
    usuario_b, token_b = criar_usuario_autenticado(data_dir)

    resposta_a = cliente.get(
        "/kyc/status",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    resposta_b = cliente.get(
        "/kyc/status",
        headers={"Authorization": f"Bearer {token_b}"},
    )

    assert resposta_a.status_code == 200
    assert resposta_b.status_code == 200
    assert resposta_a.json()["verificacaoId"] != resposta_b.json()["verificacaoId"]

    with open_db("identidade", data_dir) as conn:
        ids = dict(conn.execute("SELECT usuario_id, id FROM kyc_verificacoes").fetchall())

    assert resposta_a.json()["verificacaoId"] == ids[usuario_a]
    assert resposta_b.json()["verificacaoId"] == ids[usuario_b]


def test_documento_nao_pode_ser_registrado_apos_aprovacao(
    ambiente: tuple[TestClient, Path],
) -> None:
    cliente, data_dir = ambiente
    usuario_id, token = criar_usuario_autenticado(data_dir)

    def aprovar(conn):
        conn.execute(
            """
            UPDATE kyc_verificacoes
            SET status = 'APROVADA'
            WHERE usuario_id = ? AND status = 'PENDENTE'
            """,
            (usuario_id,),
        )

    transaction(aprovar, "identidade", data_dir)

    resposta = cliente.post(
        "/kyc/documentos",
        json={"tipo": "CPF", "numero": "12345678909"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 409

    with open_db("identidade", data_dir) as conn:
        registro = conn.execute(
            """
            SELECT status, documento_hash
            FROM kyc_verificacoes
            WHERE usuario_id = ?
            """,
            (usuario_id,),
        ).fetchone()

    assert registro == ("APROVADA", None)


def test_nova_verificacao_rejeitada_com_pendente(ambiente: tuple[TestClient, Path]) -> None:
    cliente, data_dir = ambiente
    _, token = criar_usuario_autenticado(data_dir)

    resposta = cliente.post(
        "/kyc/verificacoes",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 409


def test_nova_verificacao_apos_reprovacao(ambiente: tuple[TestClient, Path]) -> None:
    cliente, data_dir = ambiente
    usuario_id, token = criar_usuario_autenticado(data_dir)

    primeira = cliente.get(
        "/kyc/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert primeira.status_code == 200
    primeiro_id = primeira.json()["verificacaoId"]

    transaction(
        lambda conn: conn.execute(
            """
            UPDATE kyc_verificacoes
            SET status = 'REPROVADA'
            WHERE usuario_id = ? AND status = 'PENDENTE'
            """,
            (usuario_id,),
        ),
        "identidade",
        data_dir,
    )

    resposta = cliente.post(
        "/kyc/verificacoes",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 201
    assert resposta.json()["status"] == "PENDENTE"
    assert resposta.json()["verificacaoId"] != primeiro_id

    with open_db("identidade", data_dir) as conn:
        historico = conn.execute(
            """
            SELECT status
            FROM kyc_verificacoes
            WHERE usuario_id = ?
            """,
            (usuario_id,),
        ).fetchall()

    assert sorted(status for (status,) in historico) == [
        "PENDENTE",
        "REPROVADA",
    ]


def test_nova_verificacao_apos_expiracao(ambiente: tuple[TestClient, Path]) -> None:
    cliente, data_dir = ambiente
    usuario_id, token = criar_usuario_autenticado(data_dir)

    transaction(
        lambda conn: conn.execute(
            """
            UPDATE kyc_verificacoes
            SET status = 'EXPIRADA'
            WHERE usuario_id = ? AND status = 'PENDENTE'
            """,
            (usuario_id,),
        ),
        "identidade",
        data_dir,
    )

    resposta = cliente.post(
        "/kyc/verificacoes",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 201
    assert resposta.json()["status"] == "PENDENTE"


def test_nova_verificacao_rejeitada_apos_aprovacao(ambiente: tuple[TestClient, Path]) -> None:
    cliente, data_dir = ambiente
    usuario_id, token = criar_usuario_autenticado(data_dir)

    transaction(
        lambda conn: conn.execute(
            """
            UPDATE kyc_verificacoes
            SET status = 'APROVADA'
            WHERE usuario_id = ? AND status = 'PENDENTE'
            """,
            (usuario_id,),
        ),
        "identidade",
        data_dir,
    )

    resposta = cliente.post(
        "/kyc/verificacoes",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 409
