"""Testes da inicialização do microsserviço de Aportes."""

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aportes.main import app
from aportes.repository import inicializar_banco
from shared.db import open_db


def test_health_e_inicializacao_do_banco(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verifica o health check e a criação das tabelas no startup."""
    modulo = importlib.import_module("aportes.main")

    monkeypatch.setattr(
        modulo,
        "inicializar_banco",
        lambda: inicializar_banco(tmp_path),
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "aportes"

    conn = open_db("aportes", tmp_path)

    try:
        tabelas = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()

    assert {
        "aporte",
        "investidor_verificado",
        "outbox_evento",
        "evento_processado",
    }.issubset(tabelas)
