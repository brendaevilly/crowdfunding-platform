"""Testes dos endpoints HTTP da API de Notificações."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from notificacao.app import criar_notificacao_app
from notificacao.domain import Notificacao, StatusEnvio
from notificacao.repository import inicializar_banco, salvar_notificacao
from shared.auth import emitir_token
from shared.db import open_db


@pytest.fixture
def client_e_dados(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    inicializar_banco(tmp_path)
    app = criar_notificacao_app(tmp_path)
    with TestClient(app) as client:
        yield client, tmp_path


def test_listar_notificacoes_sem_autenticacao_retorna_401(
    client_e_dados: tuple[TestClient, Path],
) -> None:
    """Requisição anônima deve ser rejeitada com 401 Unauthorized."""
    client, _ = client_e_dados
    resp = client.get("/notificacoes")
    assert resp.status_code == 401


def test_listar_notificacoes_via_header_x_user_id(
    client_e_dados: tuple[TestClient, Path],
) -> None:
    """Lista notificações apenas do usuário autenticado via X-User-ID."""
    client, data_dir = client_e_dados
    u1 = "user-1"
    u2 = "user-2"

    agora = datetime.now(UTC)
    with closing(open_db("notificacao", data_dir)) as conn:
        # Notificação antiga para u1
        salvar_notificacao(
            conn,
            Notificacao(
                id=str(uuid4()),
                usuario_id=u1,
                evento_origem_id="evt-1",
                tipo_evento="aporte.confirmado",
                titulo="Notificacao Antiga",
                mensagem="Msg 1",
                status_envio=StatusEnvio.ENVIADA,
                lida=False,
                criado_em=agora - timedelta(minutes=10),
                enviado_em=agora - timedelta(minutes=10),
            ),
        )
        # Notificação recente para u1
        salvar_notificacao(
            conn,
            Notificacao(
                id=str(uuid4()),
                usuario_id=u1,
                evento_origem_id="evt-2",
                tipo_evento="campanha.resultado",
                titulo="Notificacao Recente",
                mensagem="Msg 2",
                status_envio=StatusEnvio.ENVIADA,
                lida=False,
                criado_em=agora,
                enviado_em=agora,
            ),
        )
        # Notificação para u2 (não deve vazar)
        salvar_notificacao(
            conn,
            Notificacao(
                id=str(uuid4()),
                usuario_id=u2,
                evento_origem_id="evt-3",
                tipo_evento="aporte.confirmado",
                titulo="Para Outro Usuario",
                mensagem="Msg 3",
                status_envio=StatusEnvio.ENVIADA,
                lida=False,
                criado_em=agora,
                enviado_em=agora,
            ),
        )
        conn.commit()

    resp = client.get("/notificacoes", headers={"X-User-ID": u1})
    assert resp.status_code == 200
    dados = resp.json()
    assert len(dados) == 2
    # Ordenado por criado_em DESC
    assert dados[0]["titulo"] == "Notificacao Recente"
    assert dados[1]["titulo"] == "Notificacao Antiga"
    assert dados[0]["usuarioId"] == u1
    assert dados[1]["usuarioId"] == u1


def test_listar_notificacoes_via_token_jwt(
    client_e_dados: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Autenticação com token JWT válido."""
    monkeypatch.setenv("JWT_SECRET", "segredo-testes-notificacao")
    client, data_dir = client_e_dados
    u = "user-jwt"

    with closing(open_db("notificacao", data_dir)) as conn:
        salvar_notificacao(
            conn,
            Notificacao(
                id=str(uuid4()),
                usuario_id=u,
                evento_origem_id="evt-jwt",
                tipo_evento="identidade.verificada",
                titulo="Identidade Ok",
                mensagem="Documento validado",
                status_envio=StatusEnvio.ENVIADA,
                lida=False,
                criado_em=datetime.now(UTC),
                enviado_em=datetime.now(UTC),
            ),
        )
        conn.commit()

    token = emitir_token(u, perfil="INVESTIDOR", segredo="segredo-testes-notificacao")
    resp = client.get("/notificacoes", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    dados = resp.json()
    assert len(dados) == 1
    assert dados[0]["usuarioId"] == u
    assert dados[0]["titulo"] == "Identidade Ok"


def test_marcar_notificacao_como_lida(
    client_e_dados: tuple[TestClient, Path],
) -> None:
    """Marca notificação como lida com sucesso e rejeita de outro usuário."""
    client, data_dir = client_e_dados
    u_dono = "user-dono"
    u_outro = "user-outro"
    nid = str(uuid4())

    with closing(open_db("notificacao", data_dir)) as conn:
        salvar_notificacao(
            conn,
            Notificacao(
                id=nid,
                usuario_id=u_dono,
                evento_origem_id="evt-lida",
                tipo_evento="aporte.confirmado",
                titulo="Notificacao Para Ler",
                mensagem="Ler",
                status_envio=StatusEnvio.ENVIADA,
                lida=False,
                criado_em=datetime.now(UTC),
                enviado_em=datetime.now(UTC),
            ),
        )
        conn.commit()

    # Outro usuário tenta marcar como lida (404)
    r_invasor = client.post(f"/notificacoes/{nid}/lida", headers={"X-User-ID": u_outro})
    assert r_invasor.status_code == 404

    # Dono marca como lida (200)
    r_dono = client.post(f"/notificacoes/{nid}/lida", headers={"X-User-ID": u_dono})
    assert r_dono.status_code == 200
    assert r_dono.json()["lida"] is True

    # Verifica persistência
    r_list = client.get("/notificacoes", headers={"X-User-ID": u_dono})
    assert r_list.json()[0]["lida"] is True
