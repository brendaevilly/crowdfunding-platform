"""Testes das métricas do Circuit Breaker no endpoint /health."""

import asyncio
from contextlib import suppress

from fastapi.testclient import TestClient

from shared.http.app import create_app
from shared.resilience import CircuitBreaker


def test_health_exibe_circuito_fechado() -> None:
    breaker = CircuitBreaker(failure_threshold=1)

    app = create_app(
        "servico-teste",
        configure_logs=False,
        circuit_breakers={"broker": breaker},
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["circuit_breakers"]["broker"]["state"] == "closed"


def test_health_exibe_circuito_aberto() -> None:
    breaker = CircuitBreaker(failure_threshold=1)

    async def falhar() -> None:
        raise RuntimeError("Broker indisponível")

    async def abrir_circuito() -> None:
        with suppress(RuntimeError):
            await breaker.call(falhar)

    asyncio.run(abrir_circuito())

    app = create_app(
        "servico-teste",
        configure_logs=False,
        circuit_breakers={"broker": breaker},
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["circuit_breakers"]["broker"]["state"] == "open"
    assert response.json()["circuit_breakers"]["broker"]["failure_count"] == 1


def test_health_preserva_resposta_original() -> None:
    app = create_app(
        "servico-teste",
        version="1.0.0",
        configure_logs=False,
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "servico-teste",
        "version": "1.0.0",
    }
