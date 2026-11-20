"""Testes para o job de expiração TTL de notificações e endpoint de leitura (#31)."""

from __future__ import annotations

import threading
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from notificacao.app import criar_notificacao_app
from notificacao.consumidores import consumir_aporte_confirmado
from notificacao.domain import Notificacao, StatusEnvio
from notificacao.repository import (
    inicializar_banco,
    listar_notificacoes_usuario,
    obter_notificacao_por_id,
    salvar_notificacao,
)
from notificacao.ttl import (
    limpar_notificacoes_expiradas,
    obter_ttl_dias_padrao,
    obter_ttl_intervalo_padrao,
    run_ttl_cleaner,
)
from shared.db import open_db


def test_obter_configuracoes_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica leituras de variáveis de ambiente do TTL com fallbacks seguros."""
    assert obter_ttl_dias_padrao() == 30
    assert obter_ttl_intervalo_padrao() == 3600.0

    monkeypatch.setenv("NOTIFICACAO_TTL_DIAS", "15")
    monkeypatch.setenv("NOTIFICACAO_TTL_INTERVALO_SEGUNDOS", "60")
    assert obter_ttl_dias_padrao() == 15
    assert obter_ttl_intervalo_padrao() == 60.0

    monkeypatch.setenv("NOTIFICACAO_TTL_DIAS", "invalido")
    monkeypatch.setenv("NOTIFICACAO_TTL_INTERVALO_SEGUNDOS", "invalido")
    assert obter_ttl_dias_padrao() == 30
    assert obter_ttl_intervalo_padrao() == 3600.0


def test_limpeza_ttl_remove_apenas_notificacoes_expiradas(tmp_path: Path) -> None:
    """Registros mais antigos que o TTL são apagados, preservando os recentes."""
    inicializar_banco(tmp_path)
    user_id = "user-ttl-1"
    agora = datetime.now(UTC)

    with closing(open_db("notificacao", tmp_path)) as conn:
        # 1. Notificação muito antiga (45 dias atrás) - deve ser removida
        salvar_notificacao(
            conn,
            Notificacao(
                id=str(uuid4()),
                usuario_id=user_id,
                evento_origem_id="evt-velho",
                tipo_evento="aporte.confirmado",
                titulo="Muito Antiga",
                mensagem="Expirada",
                status_envio=StatusEnvio.ENVIADA,
                lida=True,
                criado_em=agora - timedelta(days=45),
                enviado_em=agora - timedelta(days=45),
            ),
        )

        # 2. Notificação intermediária (10 dias atrás) - deve ser mantida
        salvar_notificacao(
            conn,
            Notificacao(
                id=str(uuid4()),
                usuario_id=user_id,
                evento_origem_id="evt-meio",
                tipo_evento="campanha.resultado",
                titulo="Intermediaria",
                mensagem="Valida",
                status_envio=StatusEnvio.ENVIADA,
                lida=False,
                criado_em=agora - timedelta(days=10),
                enviado_em=agora - timedelta(days=10),
            ),
        )

        # 3. Notificação recente (hoje) - deve ser mantida
        salvar_notificacao(
            conn,
            Notificacao(
                id=str(uuid4()),
                usuario_id=user_id,
                evento_origem_id="evt-novo",
                tipo_evento="retorno.distribuido",
                titulo="Recente",
                mensagem="Recente",
                status_envio=StatusEnvio.ENVIADA,
                lida=False,
                criado_em=agora,
                enviado_em=agora,
            ),
        )
        conn.commit()

    # Executa limpeza com TTL de 30 dias
    removidos = limpar_notificacoes_expiradas(tmp_path, dias_ttl=30)
    assert removidos == 1

    with closing(open_db("notificacao", tmp_path)) as conn:
        restantes = listar_notificacoes_usuario(conn, user_id)
        assert len(restantes) == 2
        titulos = {n.titulo for n in restantes}
        assert "Muito Antiga" not in titulos
        assert "Intermediaria" in titulos
        assert "Recente" in titulos


def test_expiracao_ttl_nao_afeta_idempotencia_de_eventos_recentes(tmp_path: Path) -> None:
    """A remoção de registros antigos não compromete a detecção de reentregas recentes."""
    inicializar_banco(tmp_path)
    user_id = "user-idemp"
    agora = datetime.now(UTC)

    # Cria notificação antiga e expira
    with closing(open_db("notificacao", tmp_path)) as conn:
        salvar_notificacao(
            conn,
            Notificacao(
                id=str(uuid4()),
                usuario_id=user_id,
                evento_origem_id="evt-antigo",
                tipo_evento="aporte.confirmado",
                titulo="Antiga",
                mensagem="Antiga",
                status_envio=StatusEnvio.ENVIADA,
                lida=True,
                criado_em=agora - timedelta(days=40),
            ),
        )
        conn.commit()

    limpar_notificacoes_expiradas(tmp_path, dias_ttl=30)

    # Processa evento recente
    payload_recente = {
        "aporteId": "apo-recente-1",
        "campanhaId": "camp-9",
        "investidorId": user_id,
        "valor": 30000,
        "confirmadoEm": agora.isoformat(),
    }

    with closing(open_db("notificacao", tmp_path)) as conn:
        consumir_aporte_confirmado(conn, payload_recente)
        conn.commit()

        # Reentrega imediata do evento recente deve ser ignorada
        consumir_aporte_confirmado(conn, payload_recente)
        conn.commit()

        notifs = listar_notificacoes_usuario(conn, user_id)
        assert len(notifs) == 1
        assert notifs[0].evento_origem_id == "apo-recente-1"


def test_thread_ttl_cleaner_executa_e_encerra(tmp_path: Path) -> None:
    """Verifica que a thread do job TTL executa limpeza e respeita stop signal."""
    inicializar_banco(tmp_path)
    user_id = "user-cleaner-thread"
    agora = datetime.now(UTC)

    with closing(open_db("notificacao", tmp_path)) as conn:
        salvar_notificacao(
            conn,
            Notificacao(
                id=str(uuid4()),
                usuario_id=user_id,
                evento_origem_id="evt-thread-velho",
                tipo_evento="aporte.confirmado",
                titulo="Para Apagar Pelo Job",
                mensagem="Apagar",
                status_envio=StatusEnvio.ENVIADA,
                criado_em=agora - timedelta(days=60),
            ),
        )
        conn.commit()

    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_ttl_cleaner,
        kwargs={
            "data_dir": tmp_path,
            "dias_ttl": 30,
            "intervalo_segundos": 0.1,
            "should_stop": stop_event.is_set,
        },
    )
    thread.start()

    # Dá tempo para o job executar ao menos um ciclo
    time.sleep(0.3)
    stop_event.set()
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    with closing(open_db("notificacao", tmp_path)) as conn:
        restantes = listar_notificacoes_usuario(conn, user_id)
        assert len(restantes) == 0


def test_marcar_como_lida_endpoint(tmp_path: Path) -> None:
    """Endpoint POST /notificacoes/:id/lida marca notificação e valida propriedade."""
    inicializar_banco(tmp_path)
    app = criar_notificacao_app(tmp_path)
    user_id = "user-lida-teste"
    nid = str(uuid4())

    with closing(open_db("notificacao", tmp_path)) as conn:
        salvar_notificacao(
            conn,
            Notificacao(
                id=nid,
                usuario_id=user_id,
                evento_origem_id="evt-leitura",
                tipo_evento="identidade.verificada",
                titulo="Novo Aviso",
                mensagem="Texto",
                status_envio=StatusEnvio.ENVIADA,
                lida=False,
                criado_em=datetime.now(UTC),
            ),
        )
        conn.commit()

    with TestClient(app) as client:
        # Sem auth -> 401
        r_unauth = client.post(f"/notificacoes/{nid}/lida")
        assert r_unauth.status_code == 401

        # Usuário errado -> 404
        r_outro = client.post(f"/notificacoes/{nid}/lida", headers={"X-User-ID": "outro-user"})
        assert r_outro.status_code == 404

        # Notificação inexistente -> 404
        r_inexistente = client.post(
            f"/notificacoes/{uuid4()}/lida",
            headers={"X-User-ID": user_id},
        )
        assert r_inexistente.status_code == 404

        # Dono marca como lida -> 200
        r_ok = client.post(f"/notificacoes/{nid}/lida", headers={"X-User-ID": user_id})
        assert r_ok.status_code == 200
        assert r_ok.json() == {"id": nid, "lida": True}

        # Segunda chamada é idempotente -> 200
        r_repetido = client.post(f"/notificacoes/{nid}/lida", headers={"X-User-ID": user_id})
        assert r_repetido.status_code == 200
        assert r_repetido.json() == {"id": nid, "lida": True}

    with closing(open_db("notificacao", tmp_path)) as conn:
        notificacao = obter_notificacao_por_id(conn, nid)
        assert notificacao is not None
        assert notificacao.lida is True
