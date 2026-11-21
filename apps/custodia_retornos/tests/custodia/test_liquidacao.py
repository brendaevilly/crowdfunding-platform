"""Testes financeiros da liquidação de campanhas."""

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from contracts.catalogo import ler_envelope
from contracts.eventos import CampanhaLiquidada
from custodia_retornos.custodia.dominio import (
    Movimentacao,
    TipoMovimentacao,
)
from custodia_retornos.custodia.repositorio import registrar_movimentacao
from custodia_retornos.custodia.servico_liquidacao import executar_liquidacao
from shared.db import migrate, transaction
from shared.messaging_schema import install_messaging_schema

MIGRATIONS = Path("apps/custodia_retornos/migrations")
AGORA = datetime(2026, 11, 20, tzinfo=UTC)


@pytest.fixture
def ambiente(tmp_path: Path) -> Path:
    migrate("custodia_retornos", MIGRATIONS, tmp_path)
    install_messaging_schema("custodia_retornos", tmp_path)
    return tmp_path


def preparar_campanha(
    data_dir: Path,
    resultado: str,
    aportes: tuple[tuple[str, int], ...],
) -> None:
    def operacao(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO custodia_contas (
                campanha_id, meta, prazo_fim,
                saldo_retido, empreendedor_id
            )
            VALUES (?, ?, ?, 0, ?)
            """,
            (
                "campanha-teste",
                10000,
                AGORA.isoformat(),
                "empreendedor-1",
            ),
        )

        for aporte_id, valor in aportes:
            movimentacao = Movimentacao(
                movimentacao_id=f"retencao-{aporte_id}",
                campanha_id="campanha-teste",
                aporte_id=aporte_id,
                tipo=TipoMovimentacao.RETENCAO,
                valor=valor,
                criada_em=AGORA,
            )
            assert registrar_movimentacao(conn, movimentacao)

        total = sum(valor for _, valor in aportes)

        conn.execute(
            """
            INSERT INTO custodia_resultados (
                campanha_id, resultado,
                valor_arrecadado, encerrada_em
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                "campanha-teste",
                resultado,
                total,
                AGORA.isoformat(),
            ),
        )

    transaction(operacao, "custodia_retornos", data_dir)


def consultar_estado(
    data_dir: Path,
) -> tuple[int, list[tuple[str, int, str | None]], list[tuple[str, str]]]:
    def operacao(
        conn: sqlite3.Connection,
    ) -> tuple[int, list[tuple[str, int, str | None]], list[tuple[str, str]]]:
        saldo = conn.execute(
            """
            SELECT saldo_retido
            FROM custodia_contas
            WHERE campanha_id = ?
            """,
            ("campanha-teste",),
        ).fetchone()[0]

        movimentacoes = conn.execute(
            """
            SELECT tipo, valor, aporte_id
            FROM custodia_movimentacoes
            WHERE campanha_id = ?
            ORDER BY tipo, aporte_id
            """,
            ("campanha-teste",),
        ).fetchall()

        eventos = conn.execute(
            """
            SELECT tipo_evento, payload
            FROM outbox_evento
            WHERE agregado_id = ?
            """,
            ("campanha-teste",),
        ).fetchall()

        return int(saldo), movimentacoes, eventos

    return transaction(operacao, "custodia_retornos", data_dir)


def test_liquidacao_sucesso_desconta_taxa_e_publica_evento(
    ambiente: Path,
) -> None:
    preparar_campanha(
        ambiente,
        "SUCESSO",
        (("aporte-1", 6000), ("aporte-2", 4000)),
    )

    resultado = executar_liquidacao(
        "campanha-teste",
        Decimal("10"),
        str(ambiente),
    )

    assert resultado is True

    saldo, movimentacoes, eventos = consultar_estado(ambiente)

    assert saldo == 0

    valores = {tipo: valor for tipo, valor, _ in movimentacoes if tipo in ("LIBERACAO", "TAXA")}

    assert valores == {
        "LIBERACAO": 9000,
        "TAXA": 1000,
    }

    assert len(eventos) == 1
    assert eventos[0][0] == "campanha.liquidada"

    legado = json.loads(eventos[0][1])
    envelope = ler_envelope(
        {
            "eventId": legado["eventId"],
            "topic": eventos[0][0],
            "schemaVersion": legado.get("versão", 1),
            "occurredAt": legado["ocorridoEm"],
            "correlationId": legado.get("correlationId"),
            "payload": legado["payload"],
        }
    )

    assert envelope.topic == eventos[0][0]
    assert isinstance(envelope.payload, CampanhaLiquidada)

    payload = legado["payload"]

    assert payload["campanhaId"] == "campanha-teste"
    assert payload["valorBruto"] == 10000
    assert payload["taxaPlataforma"] == 1000
    assert payload["valorLiquido"] == 9000
    assert set(payload["aportes"]) == {"aporte-1", "aporte-2"}


def test_liquidacao_falha_devolve_integralmente_cada_aporte(
    ambiente: Path,
) -> None:
    preparar_campanha(
        ambiente,
        "FALHA",
        (("aporte-1", 6000), ("aporte-2", 4000)),
    )

    resultado = executar_liquidacao(
        "campanha-teste",
        Decimal("10"),
        str(ambiente),
    )

    assert resultado is True

    saldo, movimentacoes, eventos = consultar_estado(ambiente)

    assert saldo == 0

    devolucoes = {
        aporte_id: valor for tipo, valor, aporte_id in movimentacoes if tipo == "DEVOLUCAO"
    }

    assert devolucoes == {
        "aporte-1": 6000,
        "aporte-2": 4000,
    }

    assert not any(tipo in ("LIBERACAO", "TAXA") for tipo, _, _ in movimentacoes)

    assert eventos == []


def test_liquidacao_duplicada_nao_duplica_movimentacoes_ou_eventos(
    ambiente: Path,
) -> None:
    preparar_campanha(
        ambiente,
        "SUCESSO",
        (("aporte-1", 6000), ("aporte-2", 4000)),
    )

    primeira = executar_liquidacao(
        "campanha-teste",
        Decimal("10"),
        str(ambiente),
    )

    saldo_antes, movimentacoes_antes, eventos_antes = consultar_estado(ambiente)

    segunda = executar_liquidacao(
        "campanha-teste",
        Decimal("10"),
        str(ambiente),
    )

    saldo_depois, movimentacoes_depois, eventos_depois = consultar_estado(ambiente)

    assert primeira is True
    assert segunda is False

    assert saldo_antes == saldo_depois == 0
    assert movimentacoes_antes == movimentacoes_depois
    assert eventos_antes == eventos_depois
