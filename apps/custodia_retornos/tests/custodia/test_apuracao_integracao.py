"""Integração entre consumidores, apuração e outbox."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from contracts.eventos import AporteConfirmado, CampanhaPublicada, ResultadoCampanha
from contracts.topicos import RESULTADO_CAMPANHA
from custodia_retornos.app import MIGRATIONS_DIR
from custodia_retornos.custodia.apuracao import apurar_pendentes
from custodia_retornos.custodia.clock import AdjustableClock
from custodia_retornos.custodia.consumidores import (
    consumir_aporte_confirmado,
    consumir_campanha_publicada,
)
from shared.db import migrate, transaction
from shared.messaging_schema import install_messaging_schema

SERVICE = "custodia_retornos"
AGORA = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def banco(tmp_path: Path) -> Path:
    migrate(SERVICE, MIGRATIONS_DIR, tmp_path)
    install_messaging_schema(SERVICE, tmp_path)
    return tmp_path


def publicar_campanha(
    banco: Path,
    campanha_id: str,
    empreendedor_id: str = "empreendedor-1",
    meta: int = 1000,
    prazo: datetime | None = None,
) -> None:
    evento = CampanhaPublicada(
        campanha_id=campanha_id,
        empreendedor_id=empreendedor_id,
        meta=meta,
        prazo_fim=prazo or AGORA - timedelta(seconds=1),
    )

    def executar(conn: sqlite3.Connection) -> None:
        consumir_campanha_publicada(conn, evento.model_dump(by_alias=True, mode="json"))

    transaction(executar, SERVICE, banco)


def confirmar_aporte(
    banco: Path,
    campanha_id: str,
    aporte_id: str,
    investidor_id: str,
    valor: int,
) -> None:
    evento = AporteConfirmado(
        campanha_id=campanha_id,
        aporte_id=aporte_id,
        investidor_id=investidor_id,
        valor=valor,
        confirmado_em=AGORA,
    )

    def executar(conn: sqlite3.Connection) -> None:
        consumir_aporte_confirmado(conn, evento.model_dump(by_alias=True, mode="json"))

    transaction(executar, SERVICE, banco)


def test_eventos_reais_geram_resultado_com_identificadores(
    banco: Path,
) -> None:
    publicar_campanha(banco, "campanha-1")
    confirmar_aporte(banco, "campanha-1", "aporte-1", "investidor-1", 600)
    confirmar_aporte(banco, "campanha-1", "aporte-2", "investidor-1", 400)

    clock = AdjustableClock(AGORA)

    assert apurar_pendentes(clock, banco) == 1
    assert apurar_pendentes(clock, banco) == 0

    def verificar(conn: sqlite3.Connection) -> tuple[str, str]:
        linha = conn.execute(
            """
            SELECT tipo_evento, payload
            FROM outbox_evento
            """
        ).fetchone()
        assert linha is not None
        return str(linha[0]), str(linha[1])

    topico, envelope_json = transaction(verificar, SERVICE, banco)

    assert topico == RESULTADO_CAMPANHA

    envelope = json.loads(envelope_json)
    evento = ResultadoCampanha.model_validate(envelope["payload"])

    assert evento.campanha_id == "campanha-1"
    assert evento.empreendedor_id == "empreendedor-1"
    assert evento.resultado.value == "SUCESSO"
    assert evento.valor_arrecadado == 1000
    assert evento.investidor_ids == ("investidor-1",)


def test_campanha_incompleta_nao_bloqueia_outra(
    banco: Path,
) -> None:
    def criar_antiga(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO custodia_contas (
                campanha_id, meta, prazo_fim, saldo_retido
            )
            VALUES (?, ?, ?, 0)
            """,
            (
                "campanha-antiga",
                1000,
                (AGORA - timedelta(days=1)).isoformat(),
            ),
        )

    transaction(criar_antiga, SERVICE, banco)

    publicar_campanha(banco, "campanha-valida")

    assert apurar_pendentes(AdjustableClock(AGORA), banco) == 1

    def verificar(conn: sqlite3.Connection) -> list[tuple[str]]:
        return conn.execute("SELECT campanha_id FROM custodia_resultados").fetchall()

    assert transaction(verificar, SERVICE, banco) == [("campanha-valida",)]


def test_aporte_duplicado_apos_apuracao_e_ignorado(
    banco: Path,
) -> None:
    publicar_campanha(banco, "campanha-duplicada")
    confirmar_aporte(banco, "campanha-duplicada", "aporte-1", "investidor-1", 1000)

    assert apurar_pendentes(AdjustableClock(AGORA), banco) == 1

    confirmar_aporte(banco, "campanha-duplicada", "aporte-1", "investidor-1", 1000)

    def verificar(conn: sqlite3.Connection) -> tuple[int, int]:
        retencoes = conn.execute(
            """
            SELECT COUNT(*)
            FROM custodia_movimentacoes
            WHERE tipo = 'RETENCAO'
            """
        ).fetchone()[0]

        resultados = conn.execute("SELECT COUNT(*) FROM custodia_resultados").fetchone()[0]

        return int(retencoes), int(resultados)

    assert transaction(verificar, SERVICE, banco) == (1, 1)


def test_novo_aporte_apos_apuracao_e_rejeitado(
    banco: Path,
) -> None:
    publicar_campanha(banco, "campanha-encerrada")

    assert apurar_pendentes(AdjustableClock(AGORA), banco) == 1

    with pytest.raises(ValueError, match="já foi apurada"):
        confirmar_aporte(banco, "campanha-encerrada", "aporte-novo", "investidor-2", 500)
