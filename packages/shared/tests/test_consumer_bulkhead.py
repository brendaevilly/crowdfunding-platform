"""Testes de concorrência dos consumidores de eventos."""

import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.consumer import create_events_router
from shared.messaging_schema import install_messaging_schema


def criar_evento(topic: str, event_id: str) -> dict[str, Any]:
    return {
        "eventId": event_id,
        "topic": topic,
        "payload": {
            "eventId": event_id,
            "tipo": topic,
            "versão": 1,
            "ocorridoEm": "2026-11-17T02:00:00+00:00",
            "payload": {"id": event_id},
        },
    }


def test_bulkhead_limita_concorrencia_por_topico(tmp_path: Path) -> None:
    install_messaging_schema("aportes", tmp_path)

    lock = threading.Lock()
    ativos: dict[str, int] = {"TopicoA": 0, "TopicoB": 0}
    maximos: dict[str, int] = {"TopicoA": 0, "TopicoB": 0}

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
            handlers={
                "TopicoA": criar_handler("TopicoA"),
                "TopicoB": criar_handler("TopicoB"),
            },
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
                executor.submit(enviar, topic, numero)
                for topic in ("TopicoA", "TopicoB")
                for numero in range(4)
            ]
            status_codes = [future.result() for future in futures]

    assert status_codes == [200] * 8
    assert maximos["TopicoA"] == 1
    assert maximos["TopicoB"] == 1


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
