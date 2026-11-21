"""Testes de cadastro e ativação de usuários no serviço Identidade."""

import json as jsonlib
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts.catalogo import ler_envelope
from contracts.eventos import UsuarioCadastrado
from contracts.topicos import USUARIO_CADASTRADO
from identidade.app import criar_identidade_app
from shared.db import open_db
from shared.relay import publish_pending


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Path]]:
    """Cliente HTTP com banco temporário e sem mensageria em background nos testes."""
    monkeypatch.setenv("IDENTIDADE_MESSAGING_ENABLED", "false")
    app = criar_identidade_app(data_dir=tmp_path)
    with TestClient(app) as test_client:
        yield test_client, tmp_path


def test_cadastrar_usuario_com_sucesso(client: tuple[TestClient, Path]) -> None:
    """Cadastro válido retorna 201 e status inicial PENDENTE."""
    http, data_dir = client

    payload = {
        "nome": "Brenda Evilly",
        "email": "brenda@exemplo.com",
        "senha": "senhaSegura123",
        "perfil": "EMPREENDEDOR",
    }

    resposta = http.post("/usuarios", json=payload)
    assert resposta.status_code == 201

    dados = resposta.json()
    assert "id" in dados
    assert dados["nome"] == "Brenda Evilly"
    assert dados["email"] == "brenda@exemplo.com"
    assert dados["perfil"] == "EMPREENDEDOR"
    assert dados["status"] == "PENDENTE"
    assert "criadoEm" in dados

    usuario_id = dados["id"]

    # Verifica se persistiu no banco contas_usuarios
    with closing(open_db("identidade", data_dir)) as conn:
        row = conn.execute(
            "SELECT nome, email, perfil, status FROM contas_usuarios WHERE id = ?",
            (usuario_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "Brenda Evilly"
        assert row[1] == "brenda@exemplo.com"
        assert row[2] == "EMPREENDEDOR"
        assert row[3] == "PENDENTE"

        # Verifica se o evento UsuarioCadastrado foi adicionado na outbox na mesma transação
        outbox_row = conn.execute(
            """
            SELECT agregado_id, tipo_evento, payload, status
            FROM outbox_evento
            WHERE agregado_id = ?
            """,
            (usuario_id,),
        ).fetchone()
        assert outbox_row is not None
        assert outbox_row[0] == usuario_id
        assert outbox_row[1] == USUARIO_CADASTRADO
        assert outbox_row[3] == "PENDENTE"

        # A Outbox armazena "tipo"; o catálogo espera "topic".
        dados_envelope = jsonlib.loads(outbox_row[2])
        dados_envelope["topic"] = outbox_row[1]
        dados_envelope["schemaVersion"] = dados_envelope.pop("versão")
        dados_envelope["occurredAt"] = dados_envelope.pop("ocorridoEm")
        dados_envelope.pop("tipo", None)

        # Valida o evento real da Outbox pelo catálogo oficial.
        envelope = ler_envelope(dados_envelope)
        assert isinstance(envelope.payload, UsuarioCadastrado)

        evento_payload = envelope.payload.model_dump(
            by_alias=True,
            mode="json",
        )
        assert evento_payload["usuarioId"] == usuario_id
        assert evento_payload["perfil"] == "EMPREENDEDOR"
        assert "cadastradoEm" in evento_payload


def test_cadastro_duplicado_retorna_409(client: tuple[TestClient, Path]) -> None:
    """Cadastro com mesmo e-mail retorna status 409 Conflict."""
    http, _ = client

    payload = {
        "nome": "Usuário Um",
        "email": "duplicado@exemplo.com",
        "senha": "senhaValida123",
        "perfil": "INVESTIDOR",
    }

    primeira = http.post("/usuarios", json=payload)
    assert primeira.status_code == 201

    segunda = http.post("/usuarios", json=payload)
    assert segunda.status_code == 409
    corpo = segunda.json()
    mensagem = corpo.get("error", {}).get("message", "") or corpo.get("detail", "")
    assert "E-mail já cadastrado" in mensagem


def test_cadastro_email_invalido_retorna_422(client: tuple[TestClient, Path]) -> None:
    """E-mail com formato inválido retorna 422."""
    http, _ = client

    payload = {
        "nome": "Usuário Teste",
        "email": "email-sem-formato",
        "senha": "senhaValida123",
        "perfil": "INVESTIDOR",
    }

    resposta = http.post("/usuarios", json=payload)
    assert resposta.status_code == 422


def test_cadastro_senha_curta_retorna_422(client: tuple[TestClient, Path]) -> None:
    """Senha com menos de 6 caracteres retorna 422."""
    http, _ = client

    payload = {
        "nome": "Usuário Teste",
        "email": "valido@exemplo.com",
        "senha": "123",
        "perfil": "INVESTIDOR",
    }

    resposta = http.post("/usuarios", json=payload)
    assert resposta.status_code == 422


def test_ativar_usuario_pendente(client: tuple[TestClient, Path]) -> None:
    """Ativação simples transiciona status de PENDENTE para ATIVO."""
    http, data_dir = client

    payload = {
        "nome": "Investidor Ativo",
        "email": "investidor@exemplo.com",
        "senha": "senhaValida123",
        "perfil": "INVESTIDOR",
    }

    criacao = http.post("/usuarios", json=payload)
    assert criacao.status_code == 201
    usuario_id = criacao.json()["id"]
    assert criacao.json()["status"] == "PENDENTE"

    ativacao = http.post(f"/usuarios/{usuario_id}/ativar")
    assert ativacao.status_code == 200
    assert ativacao.json()["status"] == "ATIVO"

    with closing(open_db("identidade", data_dir)) as conn:
        status_db = conn.execute(
            "SELECT status FROM contas_usuarios WHERE id = ?",
            (usuario_id,),
        ).fetchone()[0]
        assert status_db == "ATIVO"


def test_confirmar_usuario_endpoint_alternativo(client: tuple[TestClient, Path]) -> None:
    """Endpoint alternativo /confirmar também ativa o usuário."""
    http, _ = client

    payload = {
        "nome": "Empreendedor Confirmado",
        "email": "empreendedor@exemplo.com",
        "senha": "senhaValida123",
        "perfil": "EMPREENDEDOR",
    }

    criacao = http.post("/usuarios", json=payload)
    assert criacao.status_code == 201
    usuario_id = criacao.json()["id"]

    confirmacao = http.post(f"/usuarios/{usuario_id}/confirmar")
    assert confirmacao.status_code == 200
    assert confirmacao.json()["status"] == "ATIVO"


def test_ativar_usuario_inexistente_retorna_404(client: tuple[TestClient, Path]) -> None:
    """Tentar ativar usuário inexistente retorna 404."""
    http, _ = client
    resposta = http.post("/usuarios/id-inexistente/ativar")
    assert resposta.status_code == 404


def test_rota_prefixada_identidade_compativel_com_gateway(
    client: tuple[TestClient, Path],
) -> None:
    """Rotas /identidade/usuarios devem responder igual a /usuarios."""
    http, _ = client

    payload = {
        "nome": "Via Gateway",
        "email": "gateway@exemplo.com",
        "senha": "senhaValida123",
        "perfil": "EMPREENDEDOR",
    }

    resposta = http.post("/identidade/usuarios", json=payload)
    assert resposta.status_code == 201
    assert resposta.json()["email"] == "gateway@exemplo.com"


def test_evento_usuario_cadastrado_sai_pelo_broker_apos_commit(
    client: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evento UsuarioCadastrado sai pelo broker através do relay."""
    http, data_dir = client

    requisicoes_broker: list[dict[str, Any]] = []

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> httpx.Response:
        requisicoes_broker.append(json)
        return httpx.Response(
            201,
            json={"eventId": json["eventId"], "created": True, "deliveries": 1},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    payload = {
        "nome": "Empreendedor Outbox",
        "email": "outbox@exemplo.com",
        "senha": "senhaValida123",
        "perfil": "EMPREENDEDOR",
    }

    resposta = http.post("/usuarios", json=payload)
    assert resposta.status_code == 201
    usuario_id = resposta.json()["id"]

    publicados = publish_pending(
        service="identidade",
        broker_url="http://127.0.0.1:3010",
        data_dir=data_dir,
    )
    assert publicados == 1
    assert len(requisicoes_broker) == 1

    req = requisicoes_broker[0]
    assert req["topic"] == USUARIO_CADASTRADO
    envelope = req["payload"]
    assert envelope["payload"]["usuarioId"] == usuario_id
    assert envelope["payload"]["perfil"] == "EMPREENDEDOR"

    with closing(open_db("identidade", data_dir)) as conn:
        status_outbox = conn.execute(
            "SELECT status FROM outbox_evento WHERE agregado_id = ?",
            (usuario_id,),
        ).fetchone()[0]
        assert status_outbox == "PUBLICADO"
