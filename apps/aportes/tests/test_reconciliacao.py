"""Testes da reconciliação de retenções pendentes."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aportes.domain import Aporte, StatusAporte, Valor
from aportes.reconciliacao import (
    obter_prazo_reconciliacao,
    reconciliar_aportes,
)
from aportes.repository import AporteRepository, inicializar_banco
from shared.db import transaction

AGORA = datetime(2026, 11, 19, 14, 0, tzinfo=UTC)


@pytest.fixture
def banco(tmp_path: Path) -> Path:
    """Prepara o banco isolado de Aportes."""
    inicializar_banco(tmp_path)
    return tmp_path


def criar_aporte_com_pendencia(
    banco: Path,
    *,
    aporte_id: str,
    minutos_atras: int,
    status_custodia: str = "PENDENTE",
    status_aporte: StatusAporte = StatusAporte.CONFIRMADO,
) -> None:
    """Cria um aporte e sua pendência para os testes."""
    repositorio = AporteRepository(banco)
    repositorio.salvar(
        Aporte(
            id=aporte_id,
            campanha_id="campanha-1",
            investidor_id="investidor-1",
            valor=Valor(1000),
            status=status_aporte,
        )
    )

    criado_em = (AGORA - timedelta(minutes=minutos_atras)).strftime("%Y-%m-%d %H:%M:%S")

    def inserir(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO aporte_custodia (
                aporte_id, status, criado_em
            )
            VALUES (?, ?, ?)
            """,
            (aporte_id, status_custodia, criado_em),
        )

    transaction(inserir, "aportes", banco)


def consultar_pendencia(
    banco: Path,
    aporte_id: str,
) -> tuple[str, str | None]:
    """Consulta o status e a data de sinalização."""

    def consultar(conn: sqlite3.Connection) -> tuple[str, str | None]:
        registro = conn.execute(
            """
            SELECT status, sinalizado_em
            FROM aporte_custodia
            WHERE aporte_id = ?
            """,
            (aporte_id,),
        ).fetchone()

        assert registro is not None
        return str(registro[0]), registro[1]

    return transaction(consultar, "aportes", banco)


def test_sinaliza_pendencia_atrasada(banco: Path) -> None:
    criar_aporte_com_pendencia(
        banco,
        aporte_id="aporte-atrasado",
        minutos_atras=20,
    )

    resultado = reconciliar_aportes(
        data_dir=banco,
        prazo_minutos=15,
        agora=AGORA,
    )

    assert resultado.pendencias_sinalizadas == 1
    assert resultado.prazo_minutos == 15

    status, sinalizado_em = consultar_pendencia(banco, "aporte-atrasado")
    assert status == "PENDENTE"
    assert sinalizado_em is not None


def test_nao_sinaliza_pendencia_recente(banco: Path) -> None:
    criar_aporte_com_pendencia(
        banco,
        aporte_id="aporte-recente",
        minutos_atras=5,
    )

    resultado = reconciliar_aportes(
        data_dir=banco,
        prazo_minutos=15,
        agora=AGORA,
    )

    assert resultado.pendencias_sinalizadas == 0
    assert consultar_pendencia(banco, "aporte-recente") == (
        "PENDENTE",
        None,
    )


def test_reconciliacao_e_idempotente(banco: Path) -> None:
    criar_aporte_com_pendencia(
        banco,
        aporte_id="aporte-idempotente",
        minutos_atras=30,
    )

    primeira = reconciliar_aportes(
        data_dir=banco,
        prazo_minutos=15,
        agora=AGORA,
    )

    sinalizacao_original = consultar_pendencia(banco, "aporte-idempotente")[1]

    segunda = reconciliar_aportes(
        data_dir=banco,
        prazo_minutos=15,
        agora=AGORA + timedelta(minutes=10),
    )

    assert primeira.pendencias_sinalizadas == 1
    assert segunda.pendencias_sinalizadas == 0
    assert consultar_pendencia(banco, "aporte-idempotente")[1] == sinalizacao_original


def test_nao_sinaliza_pendencia_conciliada(banco: Path) -> None:
    criar_aporte_com_pendencia(
        banco,
        aporte_id="aporte-conciliado",
        minutos_atras=30,
        status_custodia="CONCILIADO",
    )

    resultado = reconciliar_aportes(
        data_dir=banco,
        prazo_minutos=15,
        agora=AGORA,
    )

    assert resultado.pendencias_sinalizadas == 0
    assert consultar_pendencia(banco, "aporte-conciliado") == (
        "CONCILIADO",
        None,
    )


def test_nao_sinaliza_aporte_rejeitado(banco: Path) -> None:
    criar_aporte_com_pendencia(
        banco,
        aporte_id="aporte-rejeitado",
        minutos_atras=30,
        status_aporte=StatusAporte.REJEITADO,
    )

    resultado = reconciliar_aportes(
        data_dir=banco,
        prazo_minutos=15,
        agora=AGORA,
    )

    assert resultado.pendencias_sinalizadas == 0
    assert consultar_pendencia(banco, "aporte-rejeitado") == (
        "PENDENTE",
        None,
    )


def test_prazo_configurado_por_ambiente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APORTES_RECONCILIACAO_MINUTOS", "30")

    assert obter_prazo_reconciliacao() == 30


@pytest.mark.parametrize("valor", ["0", "-1", "abc"])
def test_prazo_ambiente_invalido(
    monkeypatch: pytest.MonkeyPatch,
    valor: str,
) -> None:
    monkeypatch.setenv("APORTES_RECONCILIACAO_MINUTOS", valor)

    with pytest.raises(ValueError):
        obter_prazo_reconciliacao()


def test_rejeita_data_sem_fuso(banco: Path) -> None:
    with pytest.raises(ValueError):
        reconciliar_aportes(
            data_dir=banco,
            prazo_minutos=15,
            agora=datetime(2026, 11, 19, 14, 0),
        )


def test_rejeita_prazo_nao_positivo(banco: Path) -> None:
    with pytest.raises(ValueError):
        reconciliar_aportes(
            data_dir=banco,
            prazo_minutos=0,
            agora=AGORA,
        )
