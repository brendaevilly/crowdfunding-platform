"""Testes HTTP dos modos automático e manual do KYC."""

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
from shared.db import transaction


@pytest.fixture
def ambiente(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, Path]]:
    monkeypatch.setenv("IDENTIDADE_MESSAGING_ENABLED", "false")
    monkeypatch.setenv("KYC_HASH_SECRET", "segredo-testes-kyc")
    monkeypatch.setenv("JWT_SECRET", "segredo-testes-jwt")
    monkeypatch.setenv("KYC_MOCK_DELAY_SECONDS", "0")
    monkeypatch.setenv("KYC_VERIFICATION_MODE", "auto")

    app = criar_identidade_app(tmp_path)

    with TestClient(app) as cliente:
        yield cliente, tmp_path


def criar_usuario(
    data_dir: Path,
    perfil: Perfil = Perfil.INVESTIDOR,
) -> tuple[str, str]:
    usuario = cadastrar_usuario(
        nome="Usuário Teste HTTP KYC",
        email_str=f"kyc-http-{uuid4()}@exemplo.com",
        senha_plana="SenhaSegura123!",
        perfil=perfil,
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


def test_modo_auto_aprova_documento(
    ambiente: tuple[TestClient, Path],
) -> None:
    cliente, data_dir = ambiente
    _, token = criar_usuario(data_dir)

    resposta = cliente.post(
        "/kyc/documentos",
        json={"tipo": "CPF", "numero": "12345678909"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "APROVADA"
    assert resposta.json()["documentoTipo"] == "CPF"
    assert "12345678909" not in resposta.text


def test_modo_auto_reprova_documento(
    ambiente: tuple[TestClient, Path],
) -> None:
    cliente, data_dir = ambiente
    _, token = criar_usuario(data_dir)

    resposta = cliente.post(
        "/kyc/documentos",
        json={"tipo": "CPF", "numero": "12345678900"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "REPROVADA"


def test_modo_manual_mantem_documento_pendente(
    ambiente: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente, data_dir = ambiente
    monkeypatch.setenv("KYC_VERIFICATION_MODE", "manual")
    _, token = criar_usuario(data_dir)

    resposta = cliente.post(
        "/kyc/documentos",
        json={"tipo": "CPF", "numero": "12345678909"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "PENDENTE"


def test_investidor_nao_pode_decidir_kyc(
    ambiente: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente, data_dir = ambiente
    monkeypatch.setenv("KYC_VERIFICATION_MODE", "manual")

    usuario_id, token = criar_usuario(data_dir)

    cliente.post(
        "/kyc/documentos",
        json={"tipo": "CPF", "numero": "12345678909"},
        headers={"Authorization": f"Bearer {token}"},
    )

    resposta = cliente.post(
        f"/kyc/admin/verificacoes/{usuario_id}/decisao",
        json={"status": "APROVADA"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 403


def test_admin_pode_aprovar_verificacao(
    ambiente: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente, data_dir = ambiente
    monkeypatch.setenv("KYC_VERIFICATION_MODE", "manual")

    usuario_id, token_usuario = criar_usuario(data_dir)
    _, token_admin = criar_usuario(data_dir, Perfil.ADMIN)

    documento = cliente.post(
        "/kyc/documentos",
        json={"tipo": "CPF", "numero": "12345678909"},
        headers={"Authorization": f"Bearer {token_usuario}"},
    )

    assert documento.status_code == 200
    assert documento.json()["status"] == "PENDENTE"

    resposta = cliente.post(
        f"/kyc/admin/verificacoes/{usuario_id}/decisao",
        json={"status": "APROVADA"},
        headers={"Authorization": f"Bearer {token_admin}"},
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "APROVADA"


def test_admin_nao_pode_decidir_duas_vezes(
    ambiente: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente, data_dir = ambiente
    monkeypatch.setenv("KYC_VERIFICATION_MODE", "manual")

    usuario_id, token_usuario = criar_usuario(data_dir)
    _, token_admin = criar_usuario(data_dir, Perfil.ADMIN)

    cliente.post(
        "/kyc/documentos",
        json={"tipo": "CPF", "numero": "12345678909"},
        headers={"Authorization": f"Bearer {token_usuario}"},
    )

    rota = f"/kyc/admin/verificacoes/{usuario_id}/decisao"
    headers = {"Authorization": f"Bearer {token_admin}"}

    primeira = cliente.post(
        rota,
        json={"status": "APROVADA"},
        headers=headers,
    )

    segunda = cliente.post(
        rota,
        json={"status": "APROVADA"},
        headers=headers,
    )

    assert primeira.status_code == 200
    assert segunda.status_code == 409
