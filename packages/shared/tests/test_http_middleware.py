from __future__ import annotations

import json
import logging
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from shared.correlation import get_correlation_id
from shared.http import AppError, create_app
from shared.logging import JsonFormatter


class Entrada(BaseModel):
    nome: str
    valor: int


def _app() -> FastAPI:
    app = create_app("teste", version="1.2.3", configure_logs=False)

    @app.get("/cid")
    async def cid() -> dict[str, str | None]:
        return {"cid": get_correlation_id()}

    @app.post("/itens")
    async def itens(e: Entrada) -> Entrada:
        return e

    @app.get("/conflito")
    async def conflito() -> None:
        raise AppError(409, "ja_existe", "Já existe.", {"id": 1})

    @app.get("/explode")
    async def explode() -> None:
        raise RuntimeError("segredo interno")

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app())


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "teste", "version": "1.2.3"}


def test_gera_correlation_id_quando_ausente(client: TestClient) -> None:
    r = client.get("/cid")
    gerado = r.headers["x-correlation-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", gerado)
    assert r.json()["cid"] == gerado


def test_propaga_correlation_id_recebido(client: TestClient) -> None:
    r = client.get("/cid", headers={"x-correlation-id": "req-42"})
    assert r.headers["x-correlation-id"] == "req-42"
    assert r.json()["cid"] == "req-42"


def test_correlation_id_invalido_e_substituido(client: TestClient) -> None:
    r = client.get("/cid", headers={"x-correlation-id": "ruim valor\t!"})
    assert r.headers["x-correlation-id"] != "ruim valor\t!"
    assert re.fullmatch(r"[0-9a-f]{32}", r.headers["x-correlation-id"])


def test_correlation_id_nao_vaza_entre_requests(client: TestClient) -> None:
    client.get("/cid", headers={"x-correlation-id": "primeiro"})
    assert get_correlation_id() is None
    assert client.get("/cid").json()["cid"] != "primeiro"


def test_todo_log_carrega_o_correlation_id(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    client.get("/health", headers={"x-correlation-id": "log-1"})
    registros = [r for r in caplog.records if r.name == "shared.http"]
    assert registros, "o access log deveria existir"
    fmt = JsonFormatter("teste")
    # o contextvar já foi resetado; o access log é emitido dentro do contexto da requisição,
    # então confira o formato produzido ao vivo via handler dedicado.
    linhas: list[str] = []

    class Captura(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            linhas.append(fmt.format(record))

    h = Captura()
    logger = logging.getLogger("shared.http")
    logger.addHandler(h)
    try:
        client.get("/health", headers={"x-correlation-id": "log-2"})
    finally:
        logger.removeHandler(h)
    dados = json.loads(linhas[-1])
    assert dados["correlationId"] == "log-2"
    assert dados["method"] == "GET"
    assert dados["path"] == "/health"
    assert dados["status"] == 200
    assert dados["durationMs"] >= 0


def test_validacao_pydantic_422(client: TestClient) -> None:
    r = client.post(
        "/itens", json={"nome": "x", "valor": "nao-e-numero"}, headers={"x-correlation-id": "v1"}
    )
    assert r.status_code == 422
    erro = r.json()["error"]
    assert erro["code"] == "validation_error"
    assert erro["correlationId"] == "v1"
    assert erro["details"][0]["loc"] == ["body", "valor"]


def test_entrada_e_saida_validas(client: TestClient) -> None:
    r = client.post("/itens", json={"nome": "x", "valor": 3})
    assert r.status_code == 200
    assert r.json() == {"nome": "x", "valor": 3}


def test_app_error_padronizado(client: TestClient) -> None:
    r = client.get("/conflito", headers={"x-correlation-id": "c9"})
    assert r.status_code == 409
    assert r.json() == {
        "error": {
            "code": "ja_existe",
            "message": "Já existe.",
            "details": {"id": 1},
            "correlationId": "c9",
        }
    }


def test_404_padronizado(client: TestClient) -> None:
    r = client.get("/nao-existe")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    assert r.json()["error"]["correlationId"] == r.headers["x-correlation-id"]


def test_405_padronizado(client: TestClient) -> None:
    r = client.post("/health")
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "method_not_allowed"


def test_excecao_nao_tratada_vira_500_sem_vazar_detalhes(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    r = client.get("/explode", headers={"x-correlation-id": "boom-1"})
    assert r.status_code == 500
    assert r.headers["x-correlation-id"] == "boom-1"
    corpo = r.json()["error"]
    assert corpo["code"] == "internal_error"
    assert corpo["correlationId"] == "boom-1"
    assert "segredo" not in r.text
    assert any(rec.exc_info for rec in caplog.records), "a exceção deve ser logada"
