from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.http import ERROS_DE_CONEXAO, ERROS_DE_TIMEOUT, AppError, create_app


def test_app_error_com_headers() -> None:
    app = create_app("t", configure_logs=False)

    @app.get("/x")
    async def x() -> None:
        raise AppError(429, "limite", "calma", headers={"retry-after": "7"})

    r = TestClient(app).get("/x")
    assert r.status_code == 429
    assert r.headers["retry-after"] == "7"
    assert r.json()["error"]["code"] == "limite"


def test_create_app_sem_health_padrao() -> None:
    app = create_app("t", configure_logs=False, include_health=False)
    assert TestClient(app).get("/health").status_code == 404


def test_create_app_com_lifespan() -> None:
    eventos: list[str] = []

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        eventos.append("sobe")
        yield
        eventos.append("desce")

    with TestClient(create_app("t", configure_logs=False, lifespan=lifespan)) as c:
        assert c.get("/health").status_code == 200
    assert eventos == ["sobe", "desce"]


def test_grupos_de_erros_do_cliente() -> None:
    assert ERROS_DE_CONEXAO and ERROS_DE_TIMEOUT
    assert set(ERROS_DE_CONEXAO).isdisjoint(ERROS_DE_TIMEOUT)
