"""Testes da consulta ao perfil do usuário autenticado."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from identidade.app import criar_identidade_app
from identidade.contas import repositorio
from identidade.contas.dominio import StatusUsuario
from shared.auth import emitir_token
from shared.db import transaction


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Cria a Identidade com banco isolado para cada teste."""
    monkeypatch.setenv("IDENTIDADE_MESSAGING_ENABLED", "false")
    monkeypatch.setenv("IDENTIDADE_AUTO_ATIVAR", "true")
    monkeypatch.setenv("JWT_SECRET", "segredo-seguro-para-testes")

    app = criar_identidade_app(data_dir=tmp_path)

    with TestClient(app) as http:
        yield http


def cadastrar_usuario(http: TestClient) -> dict[str, str]:
    """Cadastra um investidor ativo para os testes."""
    resposta = http.post(
        "/usuarios",
        json={
            "nome": "Investidor Teste",
            "email": "investidor@exemplo.com",
            "senha": "senhaSegura123",
            "perfil": "INVESTIDOR",
        },
    )

    assert resposta.status_code == 201
    return dict(resposta.json())


def obter_token(http: TestClient) -> str:
    """Realiza login e retorna o JWT."""
    resposta = http.post(
        "/auth/login",
        json={
            "email": "investidor@exemplo.com",
            "senha": "senhaSegura123",
        },
    )

    assert resposta.status_code == 200
    return str(resposta.json()["access_token"])


def test_usuario_me_retorna_perfil_autenticado(
    client: TestClient,
) -> None:
    usuario = cadastrar_usuario(client)
    token = obter_token(client)

    resposta = client.get(
        "/usuarios/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 200

    dados = resposta.json()
    assert dados["id"] == usuario["id"]
    assert dados["nome"] == "Investidor Teste"
    assert dados["email"] == "investidor@exemplo.com"
    assert dados["perfil"] == "INVESTIDOR"
    assert dados["status"] == "ATIVO"


def test_usuario_me_nao_expoe_senha(
    client: TestClient,
) -> None:
    cadastrar_usuario(client)
    token = obter_token(client)

    resposta = client.get(
        "/usuarios/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 200
    assert "senha" not in resposta.json()
    assert "senha_hash" not in resposta.json()


def test_usuario_me_sem_token_retorna_401(
    client: TestClient,
) -> None:
    resposta = client.get("/usuarios/me")

    assert resposta.status_code == 401


def test_usuario_me_token_invalido_retorna_401(
    client: TestClient,
) -> None:
    resposta = client.get(
        "/usuarios/me",
        headers={"Authorization": "Bearer token-invalido"},
    )

    assert resposta.status_code == 401


def test_usuario_me_token_com_perfil_incorreto_retorna_401(
    client: TestClient,
) -> None:
    usuario = cadastrar_usuario(client)

    token = emitir_token(
        sub=usuario["id"],
        perfil="ADMIN",
        segredo="segredo-seguro-para-testes",
    )

    resposta = client.get(
        "/usuarios/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 401


def test_usuario_me_bloqueado_retorna_401(
    client: TestClient,
    tmp_path: Path,
) -> None:
    usuario = cadastrar_usuario(client)
    token = obter_token(client)

    # Simula o bloqueio diretamente no banco.
    # O endpoint administrativo será implementado depois.
    def bloquear(conn: object) -> None:
        import sqlite3
        from datetime import UTC, datetime

        assert isinstance(conn, sqlite3.Connection)

        repositorio.atualizar_status_usuario(
            conn,
            usuario["id"],
            StatusUsuario.BLOQUEADO,
            datetime.now(UTC),
        )

    transaction(bloquear, "identidade", tmp_path)

    resposta = client.get(
        "/usuarios/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 401


def test_usuario_me_pelo_caminho_do_gateway(
    client: TestClient,
) -> None:
    usuario = cadastrar_usuario(client)
    token = obter_token(client)

    resposta = client.get(
        "/identidade/usuarios/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 200
    assert resposta.json()["id"] == usuario["id"]
