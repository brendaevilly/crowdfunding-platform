"""Testes dos consumidores de eventos e canal simulado no serviço Notificação (#30)."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts.topicos import (
    APORTE_CONFIRMADO,
    IDENTIDADE_VERIFICADA,
    RESULTADO_CAMPANHA,
    RETORNO_DISTRIBUIDO,
)
from notificacao.consumidores import (
    consumir_aporte_confirmado,
    consumir_identidade_verificada,
    consumir_resultado_campanha,
    consumir_retorno_distribuido,
)
from notificacao.domain import StatusEnvio
from notificacao.repository import (
    inicializar_banco,
    listar_notificacoes_usuario,
)
from shared.consumer import create_events_router
from shared.db import open_db


def test_consumir_aporte_confirmado_sucesso_e_reentrega(tmp_path: Path) -> None:
    """Verifica notificação de aporte confirmado e garantia de não-duplicação na reentrega."""
    inicializar_banco(tmp_path)
    inv_id = "inv-100"
    aporte_id = f"apo-{uuid4()}"

    payload = {
        "aporteId": aporte_id,
        "campanhaId": "camp-1",
        "investidorId": inv_id,
        "valor": 50000,
        "confirmadoEm": datetime.now(UTC).isoformat(),
    }

    with closing(open_db("notificacao", tmp_path)) as conn:
        consumir_aporte_confirmado(conn, payload)
        conn.commit()

        notificacoes = listar_notificacoes_usuario(conn, inv_id)
        assert len(notificacoes) == 1
        n = notificacoes[0]
        assert n.usuario_id == inv_id
        assert n.evento_origem_id == aporte_id
        assert n.status_envio == StatusEnvio.ENVIADA
        assert n.tipo_evento == "aporte.confirmado"
        assert "500.00" in n.mensagem

        # Reentrega do mesmo evento não deve duplicar registro
        consumir_aporte_confirmado(conn, payload)
        conn.commit()

        notificacoes_apos_reentrega = listar_notificacoes_usuario(conn, inv_id)
        assert len(notificacoes_apos_reentrega) == 1


def test_consumir_resultado_campanha_notifica_empreendedor_e_investidores(tmp_path: Path) -> None:
    """Verifica que o resultado da campanha notifica tanto o empreendedor quanto os investidores."""
    inicializar_banco(tmp_path)
    emp_id = "emp-200"
    inv_1 = "inv-301"
    inv_2 = "inv-302"
    camp_id = f"camp-{uuid4()}"

    payload = {
        "campanhaId": camp_id,
        "empreendedorId": emp_id,
        "resultado": "SUCESSO",
        "valorArrecadado": 250000,
        "investidorIds": [inv_1, inv_2],
        "encerradaEm": datetime.now(UTC).isoformat(),
    }

    with closing(open_db("notificacao", tmp_path)) as conn:
        consumir_resultado_campanha(conn, payload)
        conn.commit()

        # Notificação do empreendedor
        notifs_emp = listar_notificacoes_usuario(conn, emp_id)
        assert len(notifs_emp) == 1
        assert notifs_emp[0].usuario_id == emp_id
        assert "SUCESSO" in notifs_emp[0].titulo
        assert "2500.00" in notifs_emp[0].mensagem

        # Notificações dos investidores
        notifs_inv1 = listar_notificacoes_usuario(conn, inv_1)
        assert len(notifs_inv1) == 1
        assert notifs_inv1[0].usuario_id == inv_1
        assert "SUCESSO" in notifs_inv1[0].titulo

        notifs_inv2 = listar_notificacoes_usuario(conn, inv_2)
        assert len(notifs_inv2) == 1
        assert notifs_inv2[0].usuario_id == inv_2
        assert "SUCESSO" in notifs_inv2[0].titulo

        # Reentrega do mesmo evento
        consumir_resultado_campanha(conn, payload)
        conn.commit()

        assert len(listar_notificacoes_usuario(conn, emp_id)) == 1
        assert len(listar_notificacoes_usuario(conn, inv_1)) == 1
        assert len(listar_notificacoes_usuario(conn, inv_2)) == 1


def test_consumir_retorno_distribuido(tmp_path: Path) -> None:
    """Verifica notificação de retorno financeiro distribuído."""
    inicializar_banco(tmp_path)
    inv_id = "inv-400"
    retorno_id = f"ret-{uuid4()}"

    payload = {
        "retornoId": retorno_id,
        "campanhaId": "camp-55",
        "investidorId": inv_id,
        "valor": 12000,
        "eventoOrigemId": "evt-orig-1",
        "distribuidoEm": datetime.now(UTC).isoformat(),
    }

    with closing(open_db("notificacao", tmp_path)) as conn:
        consumir_retorno_distribuido(conn, payload)
        conn.commit()

        notifs = listar_notificacoes_usuario(conn, inv_id)
        assert len(notifs) == 1
        assert notifs[0].evento_origem_id == retorno_id
        assert "120.00" in notifs[0].mensagem
        assert notifs[0].status_envio == StatusEnvio.ENVIADA


def test_consumir_identidade_verificada(tmp_path: Path) -> None:
    """Verifica notificação opcional de validação KYC de identidade."""
    inicializar_banco(tmp_path)
    user_id = "user-999"

    payload = {
        "usuarioId": user_id,
        "verificadaEm": datetime.now(UTC).isoformat(),
    }

    with closing(open_db("notificacao", tmp_path)) as conn:
        consumir_identidade_verificada(conn, payload)
        conn.commit()

        notifs = listar_notificacoes_usuario(conn, user_id)
        assert len(notifs) == 1
        assert notifs[0].tipo_evento == "identidade.verificada"
        assert notifs[0].status_envio == StatusEnvio.ENVIADA


def test_falha_de_canal_grava_falha_sem_propagar_erro(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falha de canal grava StatusEnvio.FALHA e nunca levanta exceção para o broker."""
    inicializar_banco(tmp_path)
    monkeypatch.setenv("NOTIFICACAO_SIMULAR_FALHA", "true")

    inv_id = "inv-falha"
    payload = {
        "aporteId": "apo-falha",
        "campanhaId": "camp-1",
        "investidorId": inv_id,
        "valor": 10000,
        "confirmadoEm": datetime.now(UTC).isoformat(),
    }

    with closing(open_db("notificacao", tmp_path)) as conn:
        # A chamada NÃO pode lançar exceção
        consumir_aporte_confirmado(conn, payload)
        conn.commit()

        notifs = listar_notificacoes_usuario(conn, inv_id)
        assert len(notifs) == 1
        assert notifs[0].status_envio == StatusEnvio.FALHA
        assert notifs[0].enviado_em is None


def test_consumidores_integracao_com_events_router(tmp_path: Path) -> None:
    """Testa recepção através do router POST /events e idempotência do broker."""
    inicializar_banco(tmp_path)
    inv_id = "inv-events"
    aporte_id = f"apo-{uuid4()}"

    app = FastAPI()
    app.include_router(
        create_events_router(
            service="notificacao",
            handlers={
                APORTE_CONFIRMADO: consumir_aporte_confirmado,
                RESULTADO_CAMPANHA: consumir_resultado_campanha,
                RETORNO_DISTRIBUIDO: consumir_retorno_distribuido,
                IDENTIDADE_VERIFICADA: consumir_identidade_verificada,
            },
            data_dir=tmp_path,
        )
    )

    event_id = str(uuid4())
    entrega = {
        "eventId": event_id,
        "topic": APORTE_CONFIRMADO,
        "payload": {
            "eventId": event_id,
            "tipo": APORTE_CONFIRMADO,
            "versão": 1,
            "ocorridoEm": datetime.now(UTC).isoformat(),
            "payload": {
                "aporteId": aporte_id,
                "campanhaId": "camp-10",
                "investidorId": inv_id,
                "valor": 80000,
                "confirmadoEm": datetime.now(UTC).isoformat(),
            },
        },
    }

    with TestClient(app) as client:
        # Primeira entrega processa
        r1 = client.post("/events", json=entrega)
        assert r1.status_code == 200
        assert r1.json()["processed"] is True

        with closing(open_db("notificacao", tmp_path)) as conn:
            assert len(listar_notificacoes_usuario(conn, inv_id)) == 1

        # Reentrega do broker com mesmo eventId não duplica
        r2 = client.post("/events", json=entrega)
        assert r2.status_code == 200
        assert r2.json()["processed"] is False

        with closing(open_db("notificacao", tmp_path)) as conn:
            assert len(listar_notificacoes_usuario(conn, inv_id)) == 1
