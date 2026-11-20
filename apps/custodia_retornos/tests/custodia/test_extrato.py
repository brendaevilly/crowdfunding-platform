"""Testes do extrato financeiro da custódia."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from custodia_retornos.app import criar_custodia_app
from custodia_retornos.custodia.dominio import (
    ContaCustodia,
    Movimentacao,
)
from custodia_retornos.custodia.repositorio import (
    abrir_conta,
    registrar_movimentacao,
)
from shared.db import migrate, transaction

MIGRATIONS = Path("apps/custodia_retornos/migrations")


@pytest.fixture
def cliente(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv(
        "CUSTODIA_RETORNOS_MESSAGING_ENABLED",
        "false",
    )

    migrate("custodia_retornos", MIGRATIONS, tmp_path)

    conta = ContaCustodia.abrir(
        "campanha-extrato",
        100000,
        datetime(2026, 12, 31, tzinfo=UTC),
    )

    retencao = Movimentacao.criar_retencao(
        "campanha-extrato",
        "aporte-extrato-1",
        5000,
    )

    def preparar(conn):
        abrir_conta(conn, conta)
        conn.execute(
            """
            UPDATE custodia_contas
            SET empreendedor_id = ?
            WHERE campanha_id = ?
            """,
            ("empreendedor-1", "campanha-extrato"),
        )
        registrar_movimentacao(conn, retencao)

    transaction(preparar, "custodia_retornos", tmp_path)

    app = criar_custodia_app(
        data_dir=tmp_path,
        dev_mode=False,
        scheduler_enabled=False,
    )

    with TestClient(app) as test_client:
        yield test_client


def test_extrato_retorna_conta_e_movimentacoes(cliente: TestClient) -> None:
    resposta = cliente.get("/custodia/campanhas/campanha-extrato/extrato")

    assert resposta.status_code == 200

    dados = resposta.json()

    assert dados["campanha_id"] == "campanha-extrato"
    assert dados["empreendedor_id"] == "empreendedor-1"
    assert dados["saldo_retido"] == 5000
    assert dados["liquidacao"] is None

    assert len(dados["movimentacoes"]) == 1
    assert dados["movimentacoes"][0]["tipo"] == "RETENCAO"
    assert dados["movimentacoes"][0]["valor"] == 5000


def test_extrato_de_campanha_inexistente_retorna_404(
    cliente: TestClient,
) -> None:
    resposta = cliente.get("/custodia/campanhas/inexistente/extrato")

    assert resposta.status_code == 404
