"""Testes dos consumidores de eventos de Pagamentos/Custódia no microsserviço Campanhas (#20)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from campanhas.consumidores_custodia import (
    consumir_resultado_campanha,
    consumir_total_arrecadado_atualizado,
)
from campanhas.domain import Campanha, StatusCampanha
from campanhas.repository import (
    inicializar_banco,
    obter_campanha_por_id,
    salvar_nova_campanha,
)
from contracts.topicos import RESULTADO_CAMPANHA, TOTAL_ARRECADADO_ATUALIZADO
from shared.consumer import create_events_router
from shared.db import open_db, transaction


def _criar_campanha_aux(
    data_dir: Path,
    *,
    status: StatusCampanha = StatusCampanha.PUBLICADA,
    meta: int = 1000000,
    valor_arrecadado: int = 0,
) -> str:
    """Helper para criar uma campanha de teste no banco."""
    cid = str(uuid4())
    inicio = datetime.now(UTC) - timedelta(days=2)
    fim = inicio + timedelta(days=30)
    campanha = Campanha.criar(
        empreendedor_id="emp-1",
        titulo="Campanha Custodia Teste",
        descricao="Descricao",
        meta=meta,
        prazo_inicio=inicio,
        prazo_fim=fim,
        campanha_id=cid,
    )
    campanha.status = status
    campanha.valor_arrecadado = valor_arrecadado

    def salvar(conn: sqlite3.Connection) -> None:
        salvar_nova_campanha(conn, campanha)

    transaction(salvar, "campanhas", data_dir)
    return cid


def _obter_campanha(data_dir: Path, cid: str) -> Campanha | None:
    """Helper para obter campanha abrindo conexão fechada."""
    with closing(open_db("campanhas", data_dir)) as conn:
        return obter_campanha_por_id(conn, cid)


def test_total_arrecadado_atualizacao_monotonica(tmp_path: Path) -> None:
    """Atualização só ocorre se o valor recebido for estritamente crescente."""
    inicializar_banco(tmp_path)
    cid = _criar_campanha_aux(tmp_path, valor_arrecadado=10000)

    # 1. Aumento para 50000 (deve atualizar)
    with closing(open_db("campanhas", tmp_path)) as conn:
        consumir_total_arrecadado_atualizado(
            conn,
            {
                "campanhaId": cid,
                "valorAcumulado": 50000,
            },
        )
        conn.commit()

    campanha = _obter_campanha(tmp_path, cid)
    assert campanha is not None
    assert campanha.valor_arrecadado == 50000

    # 2. Evento antigo/atrasado com 40000 (deve ser ignorado)
    with closing(open_db("campanhas", tmp_path)) as conn:
        consumir_total_arrecadado_atualizado(
            conn,
            {
                "campanhaId": cid,
                "valorAcumulado": 40000,
            },
        )
        conn.commit()

    campanha = _obter_campanha(tmp_path, cid)
    assert campanha is not None
    assert campanha.valor_arrecadado == 50000  # não regrediu

    # 3. Evento com mesmo valor 50000 (no-op)
    with closing(open_db("campanhas", tmp_path)) as conn:
        consumir_total_arrecadado_atualizado(
            conn,
            {
                "campanhaId": cid,
                "valorAcumulado": 50000,
            },
        )
        conn.commit()

    campanha = _obter_campanha(tmp_path, cid)
    assert campanha is not None
    assert campanha.valor_arrecadado == 50000

    # 4. Novo aumento para 150000 (deve atualizar)
    with closing(open_db("campanhas", tmp_path)) as conn:
        consumir_total_arrecadado_atualizado(
            conn,
            {
                "campanhaId": cid,
                "valorAcumulado": 150000,
            },
        )
        conn.commit()

    campanha = _obter_campanha(tmp_path, cid)
    assert campanha is not None
    assert campanha.valor_arrecadado == 150000


def test_total_arrecadado_campanha_inexistente(tmp_path: Path) -> None:
    """Evento para campanha inexistente é ignorado com segurança."""
    inicializar_banco(tmp_path)
    with closing(open_db("campanhas", tmp_path)) as conn:
        consumir_total_arrecadado_atualizado(
            conn,
            {
                "campanhaId": "id-nao-existe",
                "valorAcumulado": 50000,
            },
        )
        conn.commit()


def test_resultado_campanha_sucesso_e_idempotencia(tmp_path: Path) -> None:
    """Transiciona de PUBLICADA para ENCERRADA e atua como no-op em eventos subsequentes."""
    inicializar_banco(tmp_path)
    cid = _criar_campanha_aux(
        tmp_path,
        status=StatusCampanha.PUBLICADA,
        valor_arrecadado=80000,
    )
    encerrada_em = datetime.now(UTC).isoformat()

    with closing(open_db("campanhas", tmp_path)) as conn:
        # Primeiro evento: transiciona para ENCERRADA
        consumir_resultado_campanha(
            conn,
            {
                "campanhaId": cid,
                "empreendedorId": "emp-1",
                "resultado": "SUCESSO",
                "valorArrecadado": 100000,
                "investidorIds": ["inv-1", "inv-2"],
                "encerradaEm": encerrada_em,
            },
        )
        conn.commit()

        campanha = _obter_campanha(tmp_path, cid)
        assert campanha is not None
        assert campanha.status == StatusCampanha.ENCERRADA
        assert campanha.valor_arrecadado == 100000
        assert campanha.versao == 2

        # Segundo evento com mesmo campanhaId (ex: retentativa de envio de resultado)
        consumir_resultado_campanha(
            conn,
            {
                "campanhaId": cid,
                "empreendedorId": "emp-1",
                "resultado": "SUCESSO",
                "valorArrecadado": 100000,
                "investidorIds": ["inv-1", "inv-2"],
                "encerradaEm": encerrada_em,
            },
        )
        conn.commit()

        campanha_apos_duplicata = _obter_campanha(tmp_path, cid)
        assert campanha_apos_duplicata is not None
        assert campanha_apos_duplicata.status == StatusCampanha.ENCERRADA
        assert campanha_apos_duplicata.versao == 2  # No-op: não incrementou


def test_resultado_campanha_falha(tmp_path: Path) -> None:
    """Resultado FALHA também transiciona para ENCERRADA sem erro."""
    inicializar_banco(tmp_path)
    cid = _criar_campanha_aux(
        tmp_path,
        status=StatusCampanha.PUBLICADA,
        valor_arrecadado=30000,
    )

    with closing(open_db("campanhas", tmp_path)) as conn:
        consumir_resultado_campanha(
            conn,
            {
                "campanhaId": cid,
                "empreendedorId": "emp-1",
                "resultado": "FALHA",
                "valorArrecadado": 30000,
                "investidorIds": ["inv-1"],
                "encerradaEm": datetime.now(UTC).isoformat(),
            },
        )
        conn.commit()

        campanha = _obter_campanha(tmp_path, cid)
        assert campanha is not None
        assert campanha.status == StatusCampanha.ENCERRADA
        assert campanha.valor_arrecadado == 30000


def test_resultado_campanha_inexistente(tmp_path: Path) -> None:
    """Evento de resultado para campanha inexistente é ignorado com segurança."""
    inicializar_banco(tmp_path)
    with closing(open_db("campanhas", tmp_path)) as conn:
        consumir_resultado_campanha(
            conn,
            {
                "campanhaId": "id-nao-existe",
                "empreendedorId": "emp-1",
                "resultado": "FALHA",
                "valorArrecadado": 0,
                "investidorIds": [],
                "encerradaEm": datetime.now(UTC).isoformat(),
            },
        )
        conn.commit()


def test_consumidores_via_endpoint_events(tmp_path: Path) -> None:
    """Testa integração com a rota POST /events e idempotência de entrega."""
    inicializar_banco(tmp_path)
    cid = _criar_campanha_aux(
        tmp_path,
        status=StatusCampanha.PUBLICADA,
        valor_arrecadado=10000,
    )

    app = FastAPI()
    app.include_router(
        create_events_router(
            service="campanhas",
            handlers={
                TOTAL_ARRECADADO_ATUALIZADO: consumir_total_arrecadado_atualizado,
                RESULTADO_CAMPANHA: consumir_resultado_campanha,
            },
            data_dir=tmp_path,
        )
    )

    event_id_arrecadado = str(uuid4())
    entrega_arrecadado = {
        "eventId": event_id_arrecadado,
        "topic": TOTAL_ARRECADADO_ATUALIZADO,
        "payload": {
            "eventId": event_id_arrecadado,
            "tipo": TOTAL_ARRECADADO_ATUALIZADO,
            "versão": 1,
            "ocorridoEm": datetime.now(UTC).isoformat(),
            "payload": {
                "campanhaId": cid,
                "valorAcumulado": 60000,
            },
        },
    }

    with TestClient(app) as client:
        # 1. Primeira entrega de total arrecadado
        r1 = client.post("/events", json=entrega_arrecadado)
        assert r1.status_code == 200
        assert r1.json()["processed"] is True

        campanha = _obter_campanha(tmp_path, cid)
        assert campanha is not None
        assert campanha.valor_arrecadado == 60000

        # 2. Reentrega do mesmo eventId (idempotência por eventId)
        r2 = client.post("/events", json=entrega_arrecadado)
        assert r2.status_code == 200
        assert r2.json()["processed"] is False

        # 3. Entrega de ResultadoCampanha
        event_id_resultado = str(uuid4())
        entrega_resultado = {
            "eventId": event_id_resultado,
            "topic": RESULTADO_CAMPANHA,
            "payload": {
                "eventId": event_id_resultado,
                "tipo": RESULTADO_CAMPANHA,
                "versão": 1,
                "ocorridoEm": datetime.now(UTC).isoformat(),
                "payload": {
                    "campanhaId": cid,
                    "empreendedorId": "emp-1",
                    "resultado": "SUCESSO",
                    "valorArrecadado": 75000,
                    "investidorIds": ["inv-1"],
                    "encerradaEm": datetime.now(UTC).isoformat(),
                },
            },
        }

        r3 = client.post("/events", json=entrega_resultado)
        assert r3.status_code == 200
        assert r3.json()["processed"] is True

        campanha = _obter_campanha(tmp_path, cid)
        assert campanha is not None
        assert campanha.status == StatusCampanha.ENCERRADA
        assert campanha.valor_arrecadado == 75000

        # 4. Reentrega de ResultadoCampanha com novo eventId (idempotência por campanhaId)
        event_id_resultado_2 = str(uuid4())
        entrega_resultado_2 = {
            "eventId": event_id_resultado_2,
            "topic": RESULTADO_CAMPANHA,
            "payload": {
                "eventId": event_id_resultado_2,
                "tipo": RESULTADO_CAMPANHA,
                "versão": 1,
                "ocorridoEm": datetime.now(UTC).isoformat(),
                "payload": {
                    "campanhaId": cid,
                    "empreendedorId": "emp-1",
                    "resultado": "SUCESSO",
                    "valorArrecadado": 75000,
                    "investidorIds": ["inv-1"],
                    "encerradaEm": datetime.now(UTC).isoformat(),
                },
            },
        }

        r4 = client.post("/events", json=entrega_resultado_2)
        assert r4.status_code == 200
        assert r4.json()["processed"] is True  # Processed no consumer, mas no-op no banco

        campanha = _obter_campanha(tmp_path, cid)
        assert campanha is not None
        assert campanha.status == StatusCampanha.ENCERRADA


def test_consumidores_rejeitam_payloads_invalidos_via_endpoint_events(
    tmp_path: Path,
) -> None:
    """Os dois consumidores rejeitam payloads incompatíveis com os contratos."""
    inicializar_banco(tmp_path)

    app = FastAPI()
    app.include_router(
        create_events_router(
            service="campanhas",
            handlers={
                TOTAL_ARRECADADO_ATUALIZADO: consumir_total_arrecadado_atualizado,
                RESULTADO_CAMPANHA: consumir_resultado_campanha,
            },
            data_dir=tmp_path,
        )
    )

    topicos = (
        TOTAL_ARRECADADO_ATUALIZADO,
        RESULTADO_CAMPANHA,
    )

    with TestClient(app) as client:
        for topic in topicos:
            event_id = str(uuid4())

            evento = {
                "eventId": event_id,
                "topic": topic,
                "payload": {
                    "eventId": event_id,
                    "tipo": topic,
                    "versão": 1,
                    "ocorridoEm": datetime.now(UTC).isoformat(),
                    "payload": {},
                },
            }

            resposta = client.post("/events", json=evento)

            assert resposta.status_code == 422
            assert "Contrato de evento inválido" in resposta.json()["detail"]
