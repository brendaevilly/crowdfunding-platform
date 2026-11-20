"""Testes dos endpoints HTTP do microsserviço Campanhas."""

from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from campanhas.app import criar_campanhas_app
from campanhas.repository import inicializar_banco
from campanhas.usuarios_cache import (
    consumir_usuario_cadastrado,
    consumir_usuario_status_alterado,
)
from shared.db import open_db


@pytest.fixture
def client_e_dados(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    inicializar_banco(tmp_path)
    with closing(open_db("campanhas", tmp_path)) as conn:
        # Cadastra empreendedor ativo
        consumir_usuario_cadastrado(
            conn,
            {
                "usuarioId": "emp-10",
                "perfil": "EMPREENDEDOR",
                "cadastradoEm": datetime.now(UTC).isoformat(),
            },
        )

        # Cadastra empreendedor e em seguida bloqueia
        consumir_usuario_cadastrado(
            conn,
            {
                "usuarioId": "emp-bloqueado",
                "perfil": "EMPREENDEDOR",
                "cadastradoEm": datetime.now(UTC).isoformat(),
            },
        )
        consumir_usuario_status_alterado(
            conn,
            {
                "usuarioId": "emp-bloqueado",
                "statusAnterior": "ATIVO",
                "statusNovo": "BLOQUEADO",
                "alteradoEm": datetime.now(UTC).isoformat(),
            },
        )

        # Cadastra investidor
        consumir_usuario_cadastrado(
            conn,
            {
                "usuarioId": "inv-20",
                "perfil": "INVESTIDOR",
                "cadastradoEm": datetime.now(UTC).isoformat(),
            },
        )
        conn.commit()

    app = criar_campanhas_app(tmp_path)
    with TestClient(app) as client:
        yield client, tmp_path


def test_criar_campanha_com_sucesso(client_e_dados: tuple[TestClient, Path]) -> None:
    client, _ = client_e_dados
    inicio = datetime.now(UTC)
    fim = inicio + timedelta(days=30)

    resposta = client.post(
        "/campanhas",
        json={
            "titulo": "Plataforma de Reciclagem",
            "descricao": "Coleta seletiva inteligente",
            "meta": 5000000,
            "prazoInicio": inicio.isoformat(),
            "prazoFim": fim.isoformat(),
            "empreendedorId": "emp-10",
        },
        headers={"X-User-ID": "emp-10", "X-User-Perfil": "EMPREENDEDOR"},
    )

    assert resposta.status_code == 201
    dados = resposta.json()
    assert dados["id"] is not None
    assert dados["titulo"] == "Plataforma de Reciclagem"
    assert dados["meta"] == 5000000
    assert dados["status"] == "RASCUNHO"
    assert dados["versao"] == 1


def test_investidor_nao_cria_campanha(client_e_dados: tuple[TestClient, Path]) -> None:
    client, _ = client_e_dados
    inicio = datetime.now(UTC)
    fim = inicio + timedelta(days=30)

    resposta = client.post(
        "/campanhas",
        json={
            "titulo": "Tentativa Invalida",
            "descricao": "Tentativa por investidor",
            "meta": 100000,
            "prazoInicio": inicio.isoformat(),
            "prazoFim": fim.isoformat(),
            "empreendedorId": "inv-20",
        },
        headers={"X-User-ID": "inv-20"},
    )
    assert resposta.status_code == 403


def test_usuario_bloqueado_nao_cria_campanha(
    client_e_dados: tuple[TestClient, Path],
) -> None:
    client, _ = client_e_dados
    inicio = datetime.now(UTC)
    fim = inicio + timedelta(days=30)

    resposta = client.post(
        "/campanhas",
        json={
            "titulo": "Tentativa Invalida",
            "descricao": "Tentativa por bloqueado",
            "meta": 100000,
            "prazoInicio": inicio.isoformat(),
            "prazoFim": fim.isoformat(),
            "empreendedorId": "emp-bloqueado",
        },
        headers={"X-User-ID": "emp-bloqueado"},
    )
    assert resposta.status_code == 403


def test_meta_ou_prazo_invalidos_retornam_422(
    client_e_dados: tuple[TestClient, Path],
) -> None:
    client, _ = client_e_dados
    agora = datetime.now(UTC)

    # Prazo fim anterior a início
    r1 = client.post(
        "/campanhas",
        json={
            "titulo": "Teste",
            "descricao": "Teste",
            "meta": 100000,
            "prazoInicio": agora.isoformat(),
            "prazoFim": (agora - timedelta(days=1)).isoformat(),
            "empreendedorId": "emp-10",
        },
        headers={"X-User-ID": "emp-10"},
    )
    assert r1.status_code == 422

    # Meta zero ou negativa
    r2 = client.post(
        "/campanhas",
        json={
            "titulo": "Teste",
            "descricao": "Teste",
            "meta": 0,
            "prazoInicio": agora.isoformat(),
            "prazoFim": (agora + timedelta(days=10)).isoformat(),
            "empreendedorId": "emp-10",
        },
        headers={"X-User-ID": "emp-10"},
    )
    assert r2.status_code == 422


def test_obter_campanha_e_status(client_e_dados: tuple[TestClient, Path]) -> None:
    client, _ = client_e_dados
    inicio = datetime.now(UTC)
    fim = inicio + timedelta(days=15)

    criada: dict[str, Any] = client.post(
        "/campanhas",
        json={
            "titulo": "App de Mobilidade",
            "descricao": "Mobilidade urbana",
            "meta": 3000000,
            "prazoInicio": inicio.isoformat(),
            "prazoFim": fim.isoformat(),
            "empreendedorId": "emp-10",
        },
        headers={"X-User-ID": "emp-10"},
    ).json()

    cid = criada["id"]

    # GET /campanhas/{id}
    r_get = client.get(f"/campanhas/{cid}")
    assert r_get.status_code == 200
    assert r_get.json()["id"] == cid

    # GET /campanhas/{id}/status (contrato para Aportes)
    r_status = client.get(f"/campanhas/{cid}/status")
    assert r_status.status_code == 200
    status_dados = r_status.json()
    assert status_dados["campanhaId"] == cid
    assert status_dados["status"] == "RASCUNHO"


def test_editar_campanha_em_rascunho_e_concorrencia(
    client_e_dados: tuple[TestClient, Path],
) -> None:
    client, _ = client_e_dados
    inicio = datetime.now(UTC)
    fim = inicio + timedelta(days=15)

    criada: dict[str, Any] = client.post(
        "/campanhas",
        json={
            "titulo": "Campanha Original",
            "descricao": "Descricao",
            "meta": 100000,
            "prazoInicio": inicio.isoformat(),
            "prazoFim": fim.isoformat(),
            "empreendedorId": "emp-10",
        },
        headers={"X-User-ID": "emp-10"},
    ).json()

    cid = criada["id"]

    # Edição com sucesso
    r_put = client.put(
        f"/campanhas/{cid}",
        json={
            "titulo": "Campanha Atualizada",
            "descricao": "Nova Descricao",
            "meta": 200000,
            "prazoInicio": inicio.isoformat(),
            "prazoFim": (fim + timedelta(days=5)).isoformat(),
            "versao": 1,
        },
        headers={"X-User-ID": "emp-10"},
    )
    assert r_put.status_code == 200
    assert r_put.json()["versao"] == 2
    assert r_put.json()["titulo"] == "Campanha Atualizada"

    # Tentativa com versão antiga (conflito 409)
    r_conflito = client.put(
        f"/campanhas/{cid}",
        json={
            "titulo": "Concorrente",
            "descricao": "Concorrente",
            "meta": 200000,
            "prazoInicio": inicio.isoformat(),
            "prazoFim": (fim + timedelta(days=5)).isoformat(),
            "versao": 1,
        },
        headers={"X-User-ID": "emp-10"},
    )
    assert r_conflito.status_code == 409


def test_editar_campanha_por_outro_usuario_retorna_403(
    client_e_dados: tuple[TestClient, Path],
) -> None:
    client, _ = client_e_dados
    inicio = datetime.now(UTC)
    fim = inicio + timedelta(days=15)

    criada: dict[str, Any] = client.post(
        "/campanhas",
        json={
            "titulo": "Campanha Dono",
            "descricao": "Descricao",
            "meta": 100000,
            "prazoInicio": inicio.isoformat(),
            "prazoFim": fim.isoformat(),
            "empreendedorId": "emp-10",
        },
        headers={"X-User-ID": "emp-10"},
    ).json()

    cid = criada["id"]

    r_put = client.put(
        f"/campanhas/{cid}",
        json={
            "titulo": "Hack",
            "descricao": "Hack",
            "meta": 200000,
            "prazoInicio": inicio.isoformat(),
            "prazoFim": fim.isoformat(),
        },
        headers={"X-User-ID": "emp-invasor"},
    )
    assert r_put.status_code == 403
