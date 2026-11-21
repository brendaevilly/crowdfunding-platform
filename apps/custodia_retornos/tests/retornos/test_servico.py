"""Testes do serviço de criação de participações."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts.catalogo import ler_envelope
from contracts.eventos import (
    CampanhaLiquidada,
    CampanhaPublicada,
    RetornoDistribuido,
)
from contracts.topicos import RETORNO_DISTRIBUIDO
from custodia_retornos.custodia.consumidores import (
    consumir_campanha_publicada,
)
from custodia_retornos.retornos.servico import criar_participacoes
from custodia_retornos.retornos.servico_distribuicao import distribuir_retornos
from shared.db import migrate, transaction
from shared.messaging_schema import install_messaging_schema

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


@pytest.fixture
def banco(tmp_path: Path) -> Path:
    migrate("custodia_retornos", MIGRATIONS, tmp_path)
    install_messaging_schema("custodia_retornos", tmp_path)

    def preparar(conn: sqlite3.Connection) -> None:
        campanha = CampanhaPublicada(
            campanha_id="campanha-teste",
            empreendedor_id="empreendedor-1",
            meta=10000,
            prazo_fim=datetime(2026, 12, 31, tzinfo=UTC),
        )

        consumir_campanha_publicada(
            conn,
            campanha.model_dump(mode="json", by_alias=True),
        )

        conn.executemany(
            """
            INSERT INTO retornos_aportes (
                aporte_id, campanha_id, investidor_id,
                valor, confirmado_em
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("aporte-1", "campanha-teste", "investidor-1", 6000, "2026-11-20T00:00:00+00:00"),
                ("aporte-2", "campanha-teste", "investidor-1", 2000, "2026-11-20T00:00:00+00:00"),
                ("aporte-3", "campanha-teste", "investidor-2", 2000, "2026-11-20T00:00:00+00:00"),
            ],
        )

    transaction(preparar, "custodia_retornos", tmp_path)
    return tmp_path


def evento_liquidado() -> dict[str, object]:
    evento = CampanhaLiquidada(
        campanha_id="campanha-teste",
        valor_bruto=10000,
        taxa_plataforma=1000,
        valor_liquido=9000,
        liquidada_em=datetime(2026, 11, 20, tzinfo=UTC),
        aportes=("aporte-1", "aporte-2", "aporte-3"),
    )

    return evento.model_dump(mode="json", by_alias=True)


def test_cria_participacoes_agrupando_aportes(
    banco: Path,
) -> None:
    resultado = transaction(
        lambda conn: criar_participacoes(conn, evento_liquidado()),
        "custodia_retornos",
        banco,
    )

    assert resultado is True

    def consultar(conn: sqlite3.Connection) -> list[tuple[str, int, int]]:
        return [
            (str(investidor), int(valor), int(percentual))
            for investidor, valor, percentual in conn.execute(
                """
                SELECT investidor_id, valor_aportado, percentual_unidades
                FROM retornos_participacoes
                WHERE campanha_id = ?
                ORDER BY investidor_id
                """,
                ("campanha-teste",),
            ).fetchall()
        ]

    participacoes = transaction(
        consultar,
        "custodia_retornos",
        banco,
    )

    assert participacoes == [
        ("investidor-1", 8000, 800000),
        ("investidor-2", 2000, 200000),
    ]

    assert sum(item[2] for item in participacoes) == 1_000_000


def test_evento_repetido_nao_duplica_participacoes(
    banco: Path,
) -> None:
    def operacao(conn: sqlite3.Connection) -> tuple[bool, bool]:
        primeira = criar_participacoes(conn, evento_liquidado())
        segunda = criar_participacoes(conn, evento_liquidado())
        return primeira, segunda

    resultado = transaction(
        operacao,
        "custodia_retornos",
        banco,
    )

    assert resultado == (True, False)

    quantidade = transaction(
        lambda conn: conn.execute("SELECT COUNT(*) FROM retornos_participacoes").fetchone()[0],
        "custodia_retornos",
        banco,
    )

    assert quantidade == 2


def test_rejeita_aportes_que_nao_foram_registrados(
    banco: Path,
) -> None:
    evento = CampanhaLiquidada(
        campanha_id="campanha-teste",
        valor_bruto=10000,
        taxa_plataforma=1000,
        valor_liquido=9000,
        liquidada_em=datetime(2026, 11, 20, tzinfo=UTC),
        aportes=("aporte-inexistente",),
    )

    with pytest.raises(ValueError, match="não foram registrados"):
        transaction(
            lambda conn: criar_participacoes(
                conn,
                evento.model_dump(mode="json", by_alias=True),
            ),
            "custodia_retornos",
            banco,
        )


def test_rejeita_total_diferente_do_valor_bruto(
    banco: Path,
) -> None:
    evento = evento_liquidado()
    evento["valorBruto"] = 11000
    evento["valorLiquido"] = 10000

    with pytest.raises(ValueError, match="diverge"):
        transaction(
            lambda conn: criar_participacoes(conn, evento),
            "custodia_retornos",
            banco,
        )

    quantidade = transaction(
        lambda conn: conn.execute("SELECT COUNT(*) FROM retornos_participacoes").fetchone()[0],
        "custodia_retornos",
        banco,
    )

    assert quantidade == 0


def test_distribuir_retornos_publica_eventos_validos_na_outbox(
    banco: Path,
) -> None:
    """Valida os eventos reais produzidos pela distribuição financeira."""

    # Cria as participações reais dos dois investidores.
    transaction(
        lambda conn: criar_participacoes(conn, evento_liquidado()),
        "custodia_retornos",
        banco,
    )

    # Registra a liquidação bem-sucedida exigida pelo serviço.
    def registrar_liquidacao(conn: sqlite3.Connection) -> None:
        # A liquidação depende de um resultado previamente apurado.
        conn.execute(
            """
            INSERT INTO custodia_resultados (
                campanha_id,
                resultado,
                valor_arrecadado,
                encerrada_em
            )
            VALUES (?, 'SUCESSO', ?, ?)
            """,
            (
                "campanha-teste",
                10000,
                "2026-11-20T12:00:00+00:00",
            ),
        )

        conn.execute(
            """
            INSERT INTO custodia_liquidacoes (
                campanha_id,
                resultado,
                valor_bruto,
                taxa_plataforma,
                valor_liquido,
                liquidada_em
            )
            VALUES (?, 'SUCESSO', ?, ?, ?, ?)
            """,
            (
                "campanha-teste",
                10000,
                1000,
                9000,
                "2026-11-20T12:00:00+00:00",
            ),
        )

    transaction(
        registrar_liquidacao,
        "custodia_retornos",
        banco,
    )

    # Executa o produtor real e distribui o valor líquido.
    distribuicoes = transaction(
        lambda conn: distribuir_retornos(
            conn,
            campanha_id="campanha-teste",
            empreendedor_id="empreendedor-1",
            valor_total=9000,
        ),
        "custodia_retornos",
        banco,
    )

    assert {str(item["investidorId"]): int(item["valor"]) for item in distribuicoes} == {
        "investidor-1": 7200,
        "investidor-2": 1800,
    }

    # Consulta os eventos efetivamente gravados na Outbox.
    def consultar_outbox(
        conn: sqlite3.Connection,
    ) -> list[tuple[str, str]]:
        linhas = conn.execute(
            """
            SELECT tipo_evento, payload
            FROM outbox_evento
            WHERE tipo_evento = ?
            ORDER BY created_at, outbox_id
            """,
            (RETORNO_DISTRIBUIDO,),
        ).fetchall()

        return [(str(tipo), str(payload)) for tipo, payload in linhas]

    eventos = transaction(
        consultar_outbox,
        "custodia_retornos",
        banco,
    )

    assert len(eventos) == 2

    distribuicoes_por_investidor = {str(item["investidorId"]): item for item in distribuicoes}

    valores_validados: dict[str, int] = {}

    for topico, payload_json in eventos:
        legado = json.loads(payload_json)

        # Converte o envelope legado da Outbox para o envelope oficial.
        envelope = ler_envelope(
            {
                "eventId": legado["eventId"],
                "topic": legado["tipo"],
                "schemaVersion": legado["versão"],
                "occurredAt": legado["ocorridoEm"],
                "correlationId": legado["correlationId"],
                "payload": legado["payload"],
            }
        )

        assert topico == RETORNO_DISTRIBUIDO
        assert envelope.topic == RETORNO_DISTRIBUIDO
        assert isinstance(envelope.payload, RetornoDistribuido)

        payload = envelope.payload
        investidor_id = payload.investidor_id

        assert payload.campanha_id == "campanha-teste"
        assert payload.evento_origem_id
        assert investidor_id in distribuicoes_por_investidor

        esperado = distribuicoes_por_investidor[investidor_id]

        assert payload.retorno_id == str(esperado["retornoId"])
        assert payload.valor == int(esperado["valor"])

        valores_validados[investidor_id] = payload.valor

    assert valores_validados == {
        "investidor-1": 7200,
        "investidor-2": 1800,
    }
