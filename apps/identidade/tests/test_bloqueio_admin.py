"""Testes das operações administrativas de bloqueio e desbloqueio."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts.catalogo import ler_envelope
from contracts.eventos import Perfil, UsuarioStatusAlterado
from contracts.topicos import USUARIO_STATUS_ALTERADO
from identidade.app import criar_identidade_app
from identidade.contas import repositorio
from identidade.contas.servico import cadastrar_usuario
from shared.auth import emitir_token
from shared.db import open_db
from shared.relay import publish_pending


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Cria a aplicação com banco isolado para cada teste."""

    monkeypatch.setenv("IDENTIDADE_MESSAGING_ENABLED", "false")
    monkeypatch.setenv("IDENTIDADE_AUTO_ATIVAR", "true")
    monkeypatch.setenv("JWT_SECRET", "segredo-seguro-para-testes")

    app = criar_identidade_app(data_dir=tmp_path)

    with TestClient(app) as http:
        yield http


@pytest.fixture
def admin(
    tmp_path: Path,
) -> dict[str, str]:
    """Cria um administrador ativo diretamente pelo serviço."""

    usuario = cadastrar_usuario(
        nome="Administrador Teste",
        email_str="admin@exemplo.com",
        senha_plana="senhaAdmin123",
        perfil=Perfil.ADMIN,
        data_dir=tmp_path,
        auto_ativar=True,
    )

    token = emitir_token(
        sub=usuario.id,
        perfil=usuario.perfil.value,
        segredo="segredo-seguro-para-testes",
    )

    return {
        "id": usuario.id,
        "token": token,
    }


@pytest.fixture
def investidor(
    client: TestClient,
) -> dict[str, str]:
    """Cadastra um investidor ativo e obtém seu JWT."""

    resposta = client.post(
        "/usuarios",
        json={
            "nome": "Investidor Teste",
            "email": "investidor@exemplo.com",
            "senha": "senhaSegura123",
            "perfil": "INVESTIDOR",
        },
    )

    assert resposta.status_code == 201

    usuario_id = str(resposta.json()["id"])

    login = client.post(
        "/auth/login",
        json={
            "email": "investidor@exemplo.com",
            "senha": "senhaSegura123",
        },
    )

    assert login.status_code == 200

    return {
        "id": usuario_id,
        "token": str(login.json()["access_token"]),
    }


def headers(token: str) -> dict[str, str]:
    """Monta o cabeçalho de autenticação."""

    return {"Authorization": f"Bearer {token}"}


def test_admin_consegue_bloquear_usuario(
    client: TestClient,
    admin: dict[str, str],
    investidor: dict[str, str],
) -> None:
    resposta = client.post(
        f"/usuarios/{investidor['id']}/bloquear",
        headers=headers(admin["token"]),
        json={"motivo": "Violação das regras da plataforma"},
    )

    assert resposta.status_code == 200
    assert resposta.json()["id"] == investidor["id"]
    assert resposta.json()["status"] == "BLOQUEADO"


def test_admin_consegue_desbloquear_usuario(
    client: TestClient,
    admin: dict[str, str],
    investidor: dict[str, str],
) -> None:
    bloqueio = client.post(
        f"/usuarios/{investidor['id']}/bloquear",
        headers=headers(admin["token"]),
    )

    assert bloqueio.status_code == 200

    desbloqueio = client.post(
        f"/usuarios/{investidor['id']}/desbloquear",
        headers=headers(admin["token"]),
        json={"motivo": "Situação regularizada"},
    )

    assert desbloqueio.status_code == 200
    assert desbloqueio.json()["status"] == "ATIVO"


@pytest.mark.parametrize("operacao", ["bloquear", "desbloquear"])
def test_usuario_comum_nao_pode_alterar_status(
    client: TestClient,
    investidor: dict[str, str],
    operacao: str,
) -> None:
    resposta = client.post(
        f"/usuarios/{investidor['id']}/{operacao}",
        headers=headers(investidor["token"]),
    )

    assert resposta.status_code == 403


@pytest.mark.parametrize("operacao", ["bloquear", "desbloquear"])
def test_rota_admin_sem_token_retorna_401(
    client: TestClient,
    investidor: dict[str, str],
    operacao: str,
) -> None:
    resposta = client.post(
        f"/usuarios/{investidor['id']}/{operacao}",
    )

    assert resposta.status_code == 401


def test_rota_admin_token_invalido_retorna_401(
    client: TestClient,
    investidor: dict[str, str],
) -> None:
    resposta = client.post(
        f"/usuarios/{investidor['id']}/bloquear",
        headers=headers("token-invalido"),
    )

    assert resposta.status_code == 401


def test_token_com_perfil_admin_falso_retorna_401(
    client: TestClient,
    investidor: dict[str, str],
) -> None:
    token = emitir_token(
        sub=investidor["id"],
        perfil="ADMIN",
        segredo="segredo-seguro-para-testes",
    )

    resposta = client.post(
        f"/usuarios/{investidor['id']}/bloquear",
        headers=headers(token),
    )

    assert resposta.status_code == 401


def test_admin_nao_pode_bloquear_propria_conta(
    client: TestClient,
    admin: dict[str, str],
) -> None:
    resposta = client.post(
        f"/usuarios/{admin['id']}/bloquear",
        headers=headers(admin["token"]),
    )

    assert resposta.status_code == 403


def test_usuario_bloqueado_nao_pode_acessar_me(
    client: TestClient,
    admin: dict[str, str],
    investidor: dict[str, str],
) -> None:
    bloqueio = client.post(
        f"/usuarios/{investidor['id']}/bloquear",
        headers=headers(admin["token"]),
    )

    assert bloqueio.status_code == 200

    resposta = client.get(
        "/usuarios/me",
        headers=headers(investidor["token"]),
    )

    assert resposta.status_code == 401


def test_usuario_bloqueado_nao_pode_fazer_login(
    client: TestClient,
    admin: dict[str, str],
    investidor: dict[str, str],
) -> None:
    bloqueio = client.post(
        f"/usuarios/{investidor['id']}/bloquear",
        headers=headers(admin["token"]),
    )

    assert bloqueio.status_code == 200

    resposta = client.post(
        "/auth/login",
        json={
            "email": "investidor@exemplo.com",
            "senha": "senhaSegura123",
        },
    )

    assert resposta.status_code == 401


def test_bloqueio_repetido_retorna_409(
    client: TestClient,
    admin: dict[str, str],
    investidor: dict[str, str],
) -> None:
    url = f"/usuarios/{investidor['id']}/bloquear"

    primeira = client.post(
        url,
        headers=headers(admin["token"]),
    )

    segunda = client.post(
        url,
        headers=headers(admin["token"]),
    )

    assert primeira.status_code == 200
    assert segunda.status_code == 409


def test_usuario_inexistente_retorna_404(
    client: TestClient,
    admin: dict[str, str],
) -> None:
    resposta = client.post(
        "/usuarios/00000000-0000-4000-8000-000000000000/bloquear",
        headers=headers(admin["token"]),
    )

    assert resposta.status_code == 404


def test_bloqueio_atualiza_banco(
    client: TestClient,
    admin: dict[str, str],
    investidor: dict[str, str],
    tmp_path: Path,
) -> None:
    resposta = client.post(
        f"/usuarios/{investidor['id']}/bloquear",
        headers=headers(admin["token"]),
    )

    assert resposta.status_code == 200

    with closing(open_db("identidade", tmp_path)) as conn:
        usuario = repositorio.buscar_usuario_por_id(
            conn,
            investidor["id"],
        )

    assert usuario is not None
    assert usuario.status.value == "BLOQUEADO"


def test_bloqueio_registra_evento_na_outbox(
    client: TestClient,
    admin: dict[str, str],
    investidor: dict[str, str],
    tmp_path: Path,
) -> None:
    """Verifica o evento de bloqueio armazenado na outbox."""

    resposta = client.post(
        f"/usuarios/{investidor['id']}/bloquear",
        headers=headers(admin["token"]),
        json={"motivo": "Bloqueio administrativo"},
    )

    assert resposta.status_code == 200

    with closing(open_db("identidade", tmp_path)) as conn:
        cursor = conn.execute("SELECT * FROM outbox_evento")

        colunas = [coluna[0] for coluna in cursor.description or []]

        eventos = [dict(zip(colunas, linha, strict=True)) for linha in cursor.fetchall()]

    eventos_status = [
        evento for evento in eventos if USUARIO_STATUS_ALTERADO in str(evento.values())
    ]

    assert len(eventos_status) == 1

    evento = eventos_status[0]

    payload_bruto = next(
        (valor for valor in evento.values() if isinstance(valor, str) and '"statusNovo"' in valor),
        None,
    )

    assert payload_bruto is not None

    # Converte o JSON armazenado na outbox.
    evento_json = json.loads(payload_bruto)

    # Verifica os metadados do envelope.
    assert evento_json["tipo"] == USUARIO_STATUS_ALTERADO
    assert evento_json["versão"] == 1
    assert evento_json["eventId"]
    assert evento_json["correlationId"]
    assert evento_json["ocorridoEm"]

    # Os dados da alteração estão dentro de "payload".
    payload = evento_json["payload"]

    assert payload["usuarioId"] == investidor["id"]
    assert payload["statusAnterior"] == "ATIVO"
    assert payload["statusNovo"] == "BLOQUEADO"
    assert payload["motivo"] == "Bloqueio administrativo"
    assert payload["alteradoEm"]


def test_evento_usuario_status_alterado_sai_pelo_broker(
    client: TestClient,
    admin: dict[str, str],
    investidor: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publica UsuarioStatusAlterado no broker após o bloqueio."""

    requisicoes_broker: list[dict[str, Any]] = []

    def fake_post(
        url: str,
        json: dict[str, Any],
        timeout: float,
    ) -> httpx.Response:
        requisicoes_broker.append(json)

        return httpx.Response(
            201,
            json={
                "eventId": json["eventId"],
                "created": True,
                "deliveries": 1,
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    resposta = client.post(
        f"/usuarios/{investidor['id']}/bloquear",
        headers=headers(admin["token"]),
        json={"motivo": "Bloqueio administrativo"},
    )

    assert resposta.status_code == 200

    publicados = publish_pending(
        service="identidade",
        broker_url="http://127.0.0.1:3010",
        data_dir=tmp_path,
    )

    # O cadastro também gera UsuarioCadastrado.
    # Portanto, filtramos somente o evento de alteração.
    eventos_status = [
        requisicao
        for requisicao in requisicoes_broker
        if requisicao["topic"] == USUARIO_STATUS_ALTERADO
    ]

    assert publicados == len(requisicoes_broker)
    assert len(eventos_status) == 1

    requisicao = eventos_status[0]

    assert requisicao["topic"] == USUARIO_STATUS_ALTERADO

    envelope = requisicao["payload"]

    assert envelope["tipo"] == USUARIO_STATUS_ALTERADO
    assert envelope["eventId"] == requisicao["eventId"]

    # Adapta o envelope da Outbox ao formato oficial do catálogo.
    dados_envelope = dict(envelope)
    dados_envelope["topic"] = dados_envelope.pop("tipo")
    dados_envelope["schemaVersion"] = dados_envelope.pop("versão")
    dados_envelope["occurredAt"] = dados_envelope.pop("ocorridoEm")

    contrato = ler_envelope(dados_envelope)

    assert isinstance(contrato.payload, UsuarioStatusAlterado)

    payload = contrato.payload.model_dump(
        by_alias=True,
        mode="json",
    )

    assert payload["usuarioId"] == investidor["id"]
    assert payload["statusAnterior"] == "ATIVO"
    assert payload["statusNovo"] == "BLOQUEADO"
    assert payload["motivo"] == "Bloqueio administrativo"

    with closing(open_db("identidade", tmp_path)) as conn:
        status_outbox = conn.execute(
            """
            SELECT status
            FROM outbox_evento
            WHERE agregado_id = ?
              AND tipo_evento = ?
            """,
            (
                investidor["id"],
                USUARIO_STATUS_ALTERADO,
            ),
        ).fetchone()

    assert status_outbox is not None
    assert status_outbox[0] == "PUBLICADO"
