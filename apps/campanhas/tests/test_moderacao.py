"""Testes do fluxo de moderação, publicação e regra 9 (reprovada nunca vira ativa)."""

import json
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from campanhas.app import criar_campanhas_app
from campanhas.repository import inicializar_banco
from campanhas.usuarios_cache import consumir_usuario_cadastrado
from contracts.topicos import CAMPANHA_PUBLICADA
from shared.db import open_db


@pytest.fixture
def client_e_dados(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    inicializar_banco(tmp_path)
    with closing(open_db("campanhas", tmp_path)) as conn:
        consumir_usuario_cadastrado(
            conn,
            {
                "usuarioId": "emp-1",
                "perfil": "EMPREENDEDOR",
                "cadastradoEm": datetime.now(UTC).isoformat(),
            },
        )
        conn.commit()

    app = criar_campanhas_app(tmp_path)
    with TestClient(app) as client:
        yield client, tmp_path


def _criar_campanha_aux(client: TestClient, emp_id: str = "emp-1") -> str:
    inicio = datetime.now(UTC)
    fim = inicio + timedelta(days=30)
    resp = client.post(
        "/campanhas",
        json={
            "titulo": "Campanha para Moderacao",
            "descricao": "Descricao do projeto",
            "meta": 1000000,
            "prazoInicio": inicio.isoformat(),
            "prazoFim": fim.isoformat(),
            "empreendedorId": emp_id,
        },
        headers={"X-User-ID": emp_id, "X-User-Perfil": "EMPREENDEDOR"},
    )
    assert resp.status_code == 201
    return str(resp.json()["id"])


def test_submissao_campanha_para_moderacao(client_e_dados: tuple[TestClient, Path]) -> None:
    client, _ = client_e_dados
    cid = _criar_campanha_aux(client)

    # Submissão por outro usuário rejeitada com 403
    r_invasor = client.post(
        f"/campanhas/{cid}/submeter",
        headers={"X-User-ID": "outro-usuario"},
    )
    assert r_invasor.status_code == 403

    # Submissão pelo empreendedor dono com sucesso
    r_submeter = client.post(
        f"/campanhas/{cid}/submeter",
        headers={"X-User-ID": "emp-1"},
    )
    assert r_submeter.status_code == 200
    dados = r_submeter.json()
    assert dados["status"] == "EM_MODERACAO"
    assert dados["versao"] == 2

    # Nova submissão rejeitada com 409
    r_repetida = client.post(
        f"/campanhas/{cid}/submeter",
        headers={"X-User-ID": "emp-1"},
    )
    assert r_repetida.status_code == 409


def test_listagem_fila_moderacao(client_e_dados: tuple[TestClient, Path]) -> None:
    client, _ = client_e_dados
    c1 = _criar_campanha_aux(client)
    _criar_campanha_aux(client)

    client.post(f"/campanhas/{c1}/submeter", headers={"X-User-ID": "emp-1"})

    # Filtro ?status=EM_MODERACAO traz apenas c1
    r_fila = client.get("/campanhas?status=EM_MODERACAO")
    assert r_fila.status_code == 200
    itens = r_fila.json()
    assert len(itens) == 1
    assert itens[0]["id"] == c1
    assert itens[0]["status"] == "EM_MODERACAO"

    # Listagem geral traz ambas
    r_todas = client.get("/campanhas")
    assert r_todas.status_code == 200
    assert len(r_todas.json()) == 2


def test_aprovacao_e_publicacao_outbox(client_e_dados: tuple[TestClient, Path]) -> None:
    client, tmp_path = client_e_dados
    cid = _criar_campanha_aux(client)

    client.post(f"/campanhas/{cid}/submeter", headers={"X-User-ID": "emp-1"})

    # Aprovação por não-admin rejeitada com 403
    r_nao_admin = client.post(
        f"/campanhas/{cid}/aprovar",
        headers={"X-User-ID": "emp-1", "X-User-Perfil": "EMPREENDEDOR"},
    )
    assert r_nao_admin.status_code == 403

    # Aprovação por ADMIN
    r_aprovar = client.post(
        f"/campanhas/{cid}/aprovar",
        headers={
            "X-User-ID": "admin-1",
            "X-User-Perfil": "ADMIN",
            "X-Correlation-ID": "corr-aprova-1",
        },
    )
    assert r_aprovar.status_code == 200
    dados = r_aprovar.json()
    assert dados["status"] == "PUBLICADA"
    assert dados["versao"] == 3

    # Verifica status via endpoint para Aportes
    r_status = client.get(f"/campanhas/{cid}/status")
    assert r_status.status_code == 200
    assert r_status.json()["status"] == "PUBLICADA"

    # Verifica se evento CampanhaPublicada foi gravado na outbox_evento
    with closing(open_db("campanhas", tmp_path)) as conn:
        cursor = conn.execute(
            """
            SELECT agregado_id, tipo_evento, payload
            FROM outbox_evento
            WHERE agregado_id = ?
            """,
            (cid,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == cid
        assert row[1] == CAMPANHA_PUBLICADA
        envelope = json.loads(row[2])
        assert envelope["correlationId"] == "corr-aprova-1"
        payload = envelope["payload"]
        assert payload["campanhaId"] == cid
        assert payload["empreendedorId"] == "emp-1"
        assert payload["meta"] == 1000000
        assert "prazoFim" in payload

    # Edição após publicação deve ser rejeitada
    r_put = client.put(
        f"/campanhas/{cid}",
        json={
            "titulo": "Tentativa Edicao",
            "descricao": "Descricao",
            "meta": 1000000,
            "prazoInicio": datetime.now(UTC).isoformat(),
            "prazoFim": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
        },
        headers={"X-User-ID": "emp-1"},
    )
    assert r_put.status_code == 409


def test_reprovacao_e_regra_9_reprovada_nunca_vira_ativa(
    client_e_dados: tuple[TestClient, Path],
) -> None:
    client, tmp_path = client_e_dados
    cid = _criar_campanha_aux(client)

    client.post(f"/campanhas/{cid}/submeter", headers={"X-User-ID": "emp-1"})

    # Reprovação sem motivo rejeitada com 422
    r_sem_motivo = client.post(
        f"/campanhas/{cid}/reprovar",
        json={"motivo": "   "},
        headers={"X-User-ID": "admin-1", "X-User-Perfil": "ADMIN"},
    )
    assert r_sem_motivo.status_code == 422

    # Reprovação por não-admin rejeitada com 403
    r_nao_admin = client.post(
        f"/campanhas/{cid}/reprovar",
        json={"motivo": "Viola diretrizes"},
        headers={"X-User-ID": "emp-1", "X-User-Perfil": "EMPREENDEDOR"},
    )
    assert r_nao_admin.status_code == 403

    # Reprovação válida por ADMIN
    r_reprovar = client.post(
        f"/campanhas/{cid}/reprovar",
        json={"motivo": "Falta de documentação comprobatória"},
        headers={"X-User-ID": "admin-1", "X-User-Perfil": "ADMIN"},
    )
    assert r_reprovar.status_code == 200
    dados = r_reprovar.json()
    assert dados["status"] == "REPROVADA"
    assert dados["motivoReprovacao"] == "Falta de documentação comprobatória"

    # NENHUM evento CampanhaPublicada na outbox
    with closing(open_db("campanhas", tmp_path)) as conn:
        cursor = conn.execute(
            """
            SELECT COUNT(*) FROM outbox_evento WHERE agregado_id = ?
            """,
            (cid,),
        )
        assert cursor.fetchone()[0] == 0

    # REGRA 9: Campanha REPROVADA nunca pode ser aprovada ou reativada
    # 1. Tentativa de aprovar campanha reprovada -> 409
    r_tentativa_aprovar = client.post(
        f"/campanhas/{cid}/aprovar",
        headers={"X-User-ID": "admin-1", "X-User-Perfil": "ADMIN"},
    )
    assert r_tentativa_aprovar.status_code == 409
    assert "Regra 9" in r_tentativa_aprovar.json()["error"]["message"]

    # 2. Tentativa de submeter campanha reprovada -> 409
    r_tentativa_submeter = client.post(
        f"/campanhas/{cid}/submeter",
        headers={"X-User-ID": "emp-1"},
    )
    assert r_tentativa_submeter.status_code == 409

    # 3. Tentativa de editar campanha reprovada -> 409
    r_tentativa_editar = client.put(
        f"/campanhas/{cid}",
        json={
            "titulo": "Tentativa Recuperar",
            "descricao": "Descricao",
            "meta": 1000000,
            "prazoInicio": datetime.now(UTC).isoformat(),
            "prazoFim": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
        },
        headers={"X-User-ID": "emp-1"},
    )
    assert r_tentativa_editar.status_code == 409
