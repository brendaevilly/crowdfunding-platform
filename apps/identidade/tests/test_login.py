"""Testes de autenticação JWT do microsserviço Identidade."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from identidade.app import criar_identidade_app
from shared.auth import segredo_do_ambiente, validar_token


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("IDENTIDADE_MESSAGING_ENABLED", "false")
    monkeypatch.setenv("IDENTIDADE_AUTO_ATIVAR", "true")
    monkeypatch.setenv("JWT_SECRET", "segredo-seguro-para-testes")

    app = criar_identidade_app(data_dir=tmp_path)

    with TestClient(app) as http:
        yield http


def cadastrar_usuario(http: TestClient) -> dict[str, str]:
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
    return dict[str, str](resposta.json())


def test_login_retorna_jwt_valido(client: TestClient) -> None:
    usuario = cadastrar_usuario(client)

    resposta = client.post(
        "/auth/login",
        json={
            "email": "investidor@exemplo.com",
            "senha": "senhaSegura123",
        },
    )

    assert resposta.status_code == 200

    dados = resposta.json()
    assert dados["token_type"] == "bearer"

    segredo, _ = segredo_do_ambiente()
    claims = validar_token(dados["access_token"], segredo=segredo)

    assert claims.sub == usuario["id"]
    assert claims.perfil == "INVESTIDOR"


def test_login_senha_incorreta(client: TestClient) -> None:
    cadastrar_usuario(client)

    resposta = client.post(
        "/auth/login",
        json={
            "email": "investidor@exemplo.com",
            "senha": "senhaIncorreta",
        },
    )

    assert resposta.status_code == 401


def test_login_usuario_inexistente(client: TestClient) -> None:
    resposta = client.post(
        "/auth/login",
        json={
            "email": "inexistente@exemplo.com",
            "senha": "senhaSegura123",
        },
    )

    assert resposta.status_code == 401


def test_login_pelo_caminho_do_gateway(client: TestClient) -> None:
    cadastrar_usuario(client)

    resposta = client.post(
        "/identidade/login",
        json={
            "email": "investidor@exemplo.com",
            "senha": "senhaSegura123",
        },
    )

    assert resposta.status_code == 200
    assert "access_token" in resposta.json()


def test_cadastro_publico_nao_permite_admin(client: TestClient) -> None:
    resposta = client.post(
        "/usuarios",
        json={
            "nome": "Administrador Indevido",
            "email": "admin@exemplo.com",
            "senha": "senhaSegura123",
            "perfil": "ADMIN",
        },
    )

    assert resposta.status_code == 403


def test_login_usuario_pendente_ativa_automaticamente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IDENTIDADE_MESSAGING_ENABLED", "false")
    monkeypatch.setenv("IDENTIDADE_AUTO_ATIVAR", "false")
    monkeypatch.setenv("JWT_SECRET", "segredo-seguro-para-testes")

    app = criar_identidade_app(data_dir=tmp_path)
    with TestClient(app) as http:
        cad = http.post(
            "/usuarios",
            json={
                "nome": "Usuário Pendente",
                "email": "pendente@exemplo.com",
                "senha": "senhaSegura123",
                "perfil": "INVESTIDOR",
            },
        )
        assert cad.status_code == 201
        assert cad.json()["status"] == "PENDENTE"

        # Login com sucesso deve ativar o usuário e emitir token
        resposta = http.post(
            "/auth/login",
            json={
                "email": "pendente@exemplo.com",
                "senha": "senhaSegura123",
            },
        )
        assert resposta.status_code == 200
        assert "access_token" in resposta.json()

        # Verifica se o usuário agora é ATIVO
        me = http.get(
            "/usuarios/me",
            headers={"Authorization": f"Bearer {resposta.json()['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["status"] == "ATIVO"

