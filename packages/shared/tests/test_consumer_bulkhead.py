"""Testes de concorrência dos consumidores de eventos."""

import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts.eventos import AporteConfirmado, IdentidadeVerificada
from contracts.topicos import APORTE_CONFIRMADO, IDENTIDADE_VERIFICADA
from shared.consumer import create_events_router
from shared.messaging_schema import install_messaging_schema


def criar_evento(topic: str, event_id: str) -> dict[str, Any]:
    agora = datetime.now(UTC)

    if topic == APORTE_CONFIRMADO:
        aporte_contrato = AporteConfirmado(
            aporte_id=f"aporte-{event_id}",
            campanha_id="campanha-1",
            investidor_id="usuario-1",
            valor=1000,
            confirmado_em=agora,
        )
        payload_contrato = aporte_contrato.model_dump(
            by_alias=True,
            mode="json",
        )
    elif topic == IDENTIDADE_VERIFICADA:
        identidade_contrato = IdentidadeVerificada(
            usuario_id=f"usuario-{event_id}",
            verificada_em=agora,
        )
        payload_contrato = identidade_contrato.model_dump(
            by_alias=True,
            mode="json",
        )
    else:
        raise ValueError(f"Tópico não suportado no teste: {topic}")

    correlation_id = f"correlation-{event_id}"

    return {
        "eventId": event_id,
        "topic": topic,
        "correlationId": correlation_id,
        "payload": {
            "eventId": event_id,
            "tipo": topic,
            "versão": 1,
            "ocorridoEm": agora.isoformat(),
            "correlationId": correlation_id,
            "payload": payload_contrato,
        },
    }


def test_bulkhead_limita_concorrencia_por_topico(
    tmp_path: Path,
) -> None:
    install_messaging_schema("aportes", tmp_path)

    topicos = (APORTE_CONFIRMADO, IDENTIDADE_VERIFICADA)

    lock = threading.Lock()
    ativos: dict[str, int] = {topic: 0 for topic in topicos}
    maximos: dict[str, int] = {topic: 0 for topic in topicos}

    def criar_handler(
        topic: str,
    ) -> Callable[[sqlite3.Connection, dict[str, Any]], None]:
        def handler(
            conn: sqlite3.Connection,
            payload: dict[str, Any],
        ) -> None:
            del conn, payload

            with lock:
                ativos[topic] += 1
                maximos[topic] = max(maximos[topic], ativos[topic])

            try:
                time.sleep(0.02)
            finally:
                with lock:
                    ativos[topic] -= 1

        return handler

    app = FastAPI()
    app.include_router(
        create_events_router(
            service="aportes",
            handlers={topic: criar_handler(topic) for topic in topicos},
            data_dir=tmp_path,
            max_concurrent_per_topic=1,
        )
    )

    with TestClient(app) as client:

        def enviar(topic: str, numero: int) -> int:
            response = client.post(
                "/events",
                json=criar_evento(topic, f"{topic}-{numero}"),
            )
            return int(response.status_code)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(enviar, topic, numero) for topic in topicos for numero in range(4)
            ]
            status_codes = [future.result() for future in futures]

    assert status_codes == [200] * 8
    assert maximos[APORTE_CONFIRMADO] == 1
    assert maximos[IDENTIDADE_VERIFICADA] == 1


def test_bulkhead_rejeita_limite_invalido() -> None:
    try:
        create_events_router(
            service="aportes",
            handlers={},
            max_concurrent_per_topic=0,
        )
    except ValueError:
        return

    raise AssertionError("Era esperado ValueError para limite inválido")
