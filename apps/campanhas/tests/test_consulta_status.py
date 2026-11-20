"""Testes para consulta síncrona de status (Regra 2) e listagem pública com paginação."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from campanhas.app import criar_campanhas_app
from campanhas.repository import inicializar_banco
from campanhas.usuarios_cache import consumir_usuario_cadastrado
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


def _criar_e_publicar_campanha(
    client: TestClient,
    *,
    meta: int = 1000000,
    dias_fim: int = 30,
) -> str:
    inicio = datetime.now(UTC) - timedelta(days=1)
    fim = inicio + timedelta(days=dias_fim)
    resp = client.post(
        "/campanhas",
        json={
            "titulo": "Campanha Teste",
            "descricao": "Descricao",
            "meta": meta,
            "prazoInicio": inicio.isoformat(),
            "prazoFim": fim.isoformat(),
            "empreendedorId": "emp-1",
        },
        headers={"X-User-ID": "emp-1", "X-User-Perfil": "EMPREENDEDOR"},
    )
    assert resp.status_code == 201
    cid = str(resp.json()["id"])

    # Submete e aprova
    client.post(f"/campanhas/{cid}/submeter", headers={"X-User-ID": "emp-1"})
    client.post(f"/campanhas/{cid}/aprovar", headers={"X-User-Perfil": "ADMIN"})
    return cid


def test_status_sincrono_dentro_do_prazo(client_e_dados: tuple[TestClient, Path]) -> None:
    client, _ = client_e_dados
    cid = _criar_e_publicar_campanha(client, dias_fim=15)

    resp = client.get(f"/campanhas/{cid}/status")
    assert resp.status_code == 200
    dados = resp.json()
    assert dados["campanhaId"] == cid
    assert dados["status"] == "PUBLICADA"


def test_status_sincrono_fora_do_prazo_responde_encerrada_regra_2(
    client_e_dados: tuple[TestClient, Path],
) -> None:
    client, tmp_path = client_e_dados
    cid = _criar_e_publicar_campanha(client, dias_fim=10)

    # Simula passagem do tempo alterando o prazo_fim para o passado
    prazo_passado = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    with closing(open_db("campanhas", tmp_path)) as conn:
        conn.execute(
            "UPDATE campanhas SET prazo_fim = ? WHERE id = ?",
            (prazo_passado, cid),
        )
        conn.commit()

    # Mesmo com status='PUBLICADA' no banco, fora do prazo responde ENCERRADA (Regra 2)
    resp = client.get(f"/campanhas/{cid}/status")
    assert resp.status_code == 200
    dados = resp.json()
    assert dados["campanhaId"] == cid
    assert dados["status"] == "ENCERRADA"


def test_coluna_gerada_meta_atingida_nao_e_gravavel(
    client_e_dados: tuple[TestClient, Path],
) -> None:
    _, tmp_path = client_e_dados

    with closing(open_db("campanhas", tmp_path)) as conn:
        # Tentativa de INSERT explícito na coluna meta_atingida deve falhar
        with pytest.raises(sqlite3.OperationalError, match="cannot INSERT into generated column"):
            conn.execute(
                """
                INSERT INTO campanhas (
                    id, empreendedor_id, titulo, descricao, meta,
                    prazo_inicio, prazo_fim, status, valor_arrecadado,
                    meta_atingida
                )
                VALUES (
                    'c-1', 'emp-1', 'T', 'D', 100,
                    '2026-01-01', '2026-02-01', 'RASCUNHO', 50, 1
                )
                """
            )

        # Insere normalmente sem meta_atingida
        conn.execute(
            """
            INSERT INTO campanhas (
                id, empreendedor_id, titulo, descricao, meta,
                prazo_inicio, prazo_fim, status, valor_arrecadado
            )
            VALUES ('c-1', 'emp-1', 'T', 'D', 100, '2026-01-01', '2026-02-01', 'RASCUNHO', 50)
            """
        )
        conn.commit()

        # meta_atingida deve ser 0 pois 50 < 100
        row = conn.execute("SELECT meta_atingida FROM campanhas WHERE id = 'c-1'").fetchone()
        assert row[0] == 0

        # Atualiza valor_arrecadado para 150 (>= 100)
        conn.execute("UPDATE campanhas SET valor_arrecadado = 150 WHERE id = 'c-1'")
        conn.commit()

        # meta_atingida deve derivar 1 automaticamente
        row = conn.execute("SELECT meta_atingida FROM campanhas WHERE id = 'c-1'").fetchone()
        assert row[0] == 1


def test_listagem_publica_paginacao_e_meta_atingida(
    client_e_dados: tuple[TestClient, Path],
) -> None:
    client, tmp_path = client_e_dados
    c1 = _criar_e_publicar_campanha(client, meta=1000)
    c2 = _criar_e_publicar_campanha(client, meta=5000)

    # Simula c1 com meta atingida (valor_arrecadado = 1500)
    with closing(open_db("campanhas", tmp_path)) as conn:
        conn.execute("UPDATE campanhas SET valor_arrecadado = 1500 WHERE id = ?", (c1,))
        conn.commit()

    # Consulta com limite de 1 item
    r_pag1 = client.get("/campanhas?status=ATIVA&limite=1&offset=0")
    assert r_pag1.status_code == 200
    itens1 = r_pag1.json()
    assert len(itens1) == 1

    # Consulta com offset de 1
    r_pag2 = client.get("/campanhas?status=ATIVA&limite=1&offset=1")
    assert r_pag2.status_code == 200
    itens2 = r_pag2.json()
    assert len(itens2) == 1
    assert itens1[0]["id"] != itens2[0]["id"]

    # Consulta completa e valida metaAtingida
    r_todas = client.get("/campanhas?status=PUBLICADA")
    assert r_todas.status_code == 200
    itens = {c["id"]: c for c in r_todas.json()}
    assert itens[c1]["metaAtingida"] is True
    assert itens[c1]["meta_atingida"] is True
    assert itens[c2]["metaAtingida"] is False
    assert itens[c2]["meta_atingida"] is False
