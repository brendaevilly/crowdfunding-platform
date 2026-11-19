"""Testes de persistência e migrations de Aportes."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from aportes.domain import Aporte, Valor
from aportes.repository import AporteRepository, inicializar_banco
from shared.db import open_db


@pytest.fixture
def banco(tmp_path: Path) -> Path:
    inicializar_banco(tmp_path)
    return tmp_path


def criar_aporte() -> Aporte:
    return Aporte(
        id="aporte-1",
        campanha_id="campanha-1",
        investidor_id="investidor-1",
        valor=Valor(2500),
    )


def test_migrations_criam_tabelas(banco: Path) -> None:
    with closing(open_db("aportes", banco)) as conn:
        tabelas = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

    assert {
        "aporte",
        "investidor_verificado",
        "aporte_requisicao",
        "investidor_status",
        "outbox_evento",
        "evento_processado",
    }.issubset(tabelas)


@pytest.mark.parametrize("valor", [0, -1, -100])
def test_banco_rejeita_aporte_invalido(
    banco: Path,
    valor: int,
) -> None:
    with closing(open_db("aportes", banco)) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO aporte (
                id,
                campanha_id,
                investidor_id,
                valor,
                status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                f"aporte-{valor}",
                "campanha-1",
                "investidor-1",
                valor,
                "PENDENTE",
            ),
        )


def test_salvar_e_buscar_aporte(banco: Path) -> None:
    repo = AporteRepository(banco)
    aporte = criar_aporte()

    repo.salvar(aporte)
    encontrado = repo.buscar_por_id(aporte.id)

    assert encontrado == aporte


def test_buscar_aporte_inexistente(banco: Path) -> None:
    repo = AporteRepository(banco)

    assert repo.buscar_por_id("inexistente") is None


def test_confirmar_aporte_persistido(banco: Path) -> None:
    repo = AporteRepository(banco)
    aporte = criar_aporte()

    repo.salvar(aporte)
    repo.salvar(aporte.confirmar())

    encontrado = repo.buscar_por_id(aporte.id)

    assert encontrado == aporte.confirmar()


def test_nao_alterar_valor_confirmado(banco: Path) -> None:
    repo = AporteRepository(banco)
    confirmado = criar_aporte().confirmar()

    repo.salvar(confirmado)

    alterado = Aporte(
        id=confirmado.id,
        campanha_id=confirmado.campanha_id,
        investidor_id=confirmado.investidor_id,
        valor=Valor(5000),
        status=confirmado.status,
    )

    with pytest.raises(ValueError):
        repo.salvar(alterado)

    assert repo.buscar_por_id(confirmado.id) == confirmado


def test_migrations_sao_idempotentes(banco: Path) -> None:
    """Verifica que executar migrations novamente não cria duplicações."""
    inicializar_banco(banco)
    inicializar_banco(banco)

    with closing(open_db("aportes", banco)) as conn:
        quantidade = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()

    assert quantidade is not None
    assert quantidade[0] == 5


def test_aporte_confirmado_nao_pode_voltar_a_pendente(
    banco: Path,
) -> None:
    repo = AporteRepository(banco)
    confirmado = criar_aporte().confirmar()
    repo.salvar(confirmado)

    pendente = criar_aporte()

    with pytest.raises(ValueError, match="finalizado"):
        repo.salvar(pendente)

    assert repo.buscar_por_id(confirmado.id) == confirmado


def test_aporte_rejeitado_nao_pode_ser_confirmado(
    banco: Path,
) -> None:
    repo = AporteRepository(banco)
    rejeitado = criar_aporte().rejeitar()
    repo.salvar(rejeitado)

    confirmado = criar_aporte().confirmar()

    with pytest.raises(ValueError, match="finalizado"):
        repo.salvar(confirmado)

    assert repo.buscar_por_id(rejeitado.id) == rejeitado


def test_nao_permite_alterar_identificadores(
    banco: Path,
) -> None:
    repo = AporteRepository(banco)
    original = criar_aporte()
    repo.salvar(original)

    alterado = Aporte(
        id=original.id,
        campanha_id="outra-campanha",
        investidor_id=original.investidor_id,
        valor=original.valor,
    )

    with pytest.raises(ValueError, match="identificadores"):
        repo.salvar(alterado)

    assert repo.buscar_por_id(original.id) == original


def test_salvar_aporte_finalizado_sem_alteracoes(
    banco: Path,
) -> None:
    repo = AporteRepository(banco)
    confirmado = criar_aporte().confirmar()

    repo.salvar(confirmado)
    repo.salvar(confirmado)

    assert repo.buscar_por_id(confirmado.id) == confirmado
