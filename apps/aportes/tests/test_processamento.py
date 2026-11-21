"""Testes de persistência transacional e idempotência de aportes."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest

import aportes.processamento as processamento
from aportes.processamento import (
    ChaveIdempotenciaConflitante,
    ResultadoAporte,
    confirmar_aporte,
)
from aportes.repository import inicializar_banco
from contracts.catalogo import ler_envelope
from contracts.eventos import AporteConfirmado, TotalArrecadadoAtualizado
from contracts.topicos import APORTE_CONFIRMADO, TOTAL_ARRECADADO_ATUALIZADO
from shared.db import transaction
from shared.outbox import OutboxEvent
from shared.outbox import add as adicionar_evento_original


def consultar_banco(data_dir: Path) -> tuple[int, int, int, int]:
    """Conta aportes, eventos, requisições e total confirmado."""

    def consultar(conn: sqlite3.Connection) -> tuple[int, int, int, int]:
        aportes = conn.execute("SELECT COUNT(*) FROM aporte").fetchone()[0]

        eventos = conn.execute("SELECT COUNT(*) FROM outbox_evento").fetchone()[0]

        requisicoes = conn.execute("SELECT COUNT(*) FROM aporte_requisicao").fetchone()[0]

        total = conn.execute(
            """
            SELECT COALESCE(SUM(valor), 0)
            FROM aporte
            WHERE status = 'CONFIRMADO'
            """
        ).fetchone()[0]

        return int(aportes), int(eventos), int(requisicoes), int(total)

    return transaction(consultar, "aportes", data_dir)


def criar_aporte(
    data_dir: Path,
    chave: str = "chave-1",
    valor: int = 5000,
) -> ResultadoAporte:
    """Cria um aporte confirmado para os testes."""

    return confirmar_aporte(
        idempotency_key=chave,
        campanha_id="campanha-1",
        investidor_id="investidor-1",
        valor_centavos=valor,
        correlation_id="teste-correlation",
        data_dir=data_dir,
    )


def test_confirma_aporte_e_registra_eventos(tmp_path: Path) -> None:
    """Verifica a confirmação e o registro dos eventos na outbox."""

    inicializar_banco(tmp_path)

    resultado = criar_aporte(tmp_path)

    assert resultado.status_http == 201
    assert resultado.resposta["status"] == "CONFIRMADO"
    assert consultar_banco(tmp_path) == (1, 2, 1, 5000)


def test_mesma_chave_nao_duplica_aporte(tmp_path: Path) -> None:
    """Garante que a mesma chave não gere aportes duplicados."""

    inicializar_banco(tmp_path)

    primeiro = criar_aporte(tmp_path)
    segundo = criar_aporte(tmp_path)

    assert primeiro == segundo
    assert consultar_banco(tmp_path) == (1, 2, 1, 5000)


def test_chave_reutilizada_com_dados_diferentes_falha(
    tmp_path: Path,
) -> None:
    """Impede reutilizar uma chave com dados diferentes."""

    inicializar_banco(tmp_path)
    criar_aporte(tmp_path)

    with pytest.raises(ChaveIdempotenciaConflitante):
        criar_aporte(tmp_path, valor=9000)

    assert consultar_banco(tmp_path) == (1, 2, 1, 5000)


def test_total_arrecadado_e_acumulativo(tmp_path: Path) -> None:
    """Verifica se o total arrecadado aumenta a cada aporte."""

    inicializar_banco(tmp_path)

    criar_aporte(tmp_path, chave="chave-1", valor=5000)
    criar_aporte(tmp_path, chave="chave-2", valor=3000)

    assert consultar_banco(tmp_path) == (2, 4, 2, 8000)

    def buscar_totais(conn: sqlite3.Connection) -> list[int]:
        registros = conn.execute(
            """
            SELECT payload
            FROM outbox_evento
            WHERE tipo_evento = 'campanha.total-arrecadado-atualizado'
            ORDER BY rowid
            """
        ).fetchall()

        return [int(json.loads(registro[0])["payload"]["valorAcumulado"]) for registro in registros]

    totais = transaction(buscar_totais, "aportes", tmp_path)

    assert totais == [5000, 8000]


def test_requisicoes_simultaneas_mesma_chave_nao_duplicam(
    tmp_path: Path,
) -> None:
    """Duas operações concorrentes com a mesma chave criam um único aporte."""

    inicializar_banco(tmp_path)

    barreira = Barrier(2)

    def executar() -> ResultadoAporte:
        barreira.wait(timeout=10)

        return criar_aporte(
            tmp_path,
            chave="chave-concorrente",
            valor=5000,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futuro_1 = executor.submit(executar)
        futuro_2 = executor.submit(executar)

        primeiro = futuro_1.result(timeout=15)
        segundo = futuro_2.result(timeout=15)

    assert primeiro.status_http == 201
    assert segundo.status_http == 201
    assert primeiro == segundo
    assert consultar_banco(tmp_path) == (1, 2, 1, 5000)


def test_requisicoes_simultaneas_chaves_diferentes(
    tmp_path: Path,
) -> None:
    """Aportes concorrentes distintos preservam o total arrecadado."""

    inicializar_banco(tmp_path)

    barreira = Barrier(2)

    def executar(chave: str, valor: int) -> ResultadoAporte:
        barreira.wait(timeout=10)

        return criar_aporte(
            tmp_path,
            chave=chave,
            valor=valor,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futuro_1 = executor.submit(
            executar,
            "chave-concorrente-1",
            5000,
        )
        futuro_2 = executor.submit(
            executar,
            "chave-concorrente-2",
            3000,
        )

        primeiro = futuro_1.result(timeout=15)
        segundo = futuro_2.result(timeout=15)

    assert primeiro.status_http == 201
    assert segundo.status_http == 201

    assert primeiro.resposta["aporteId"] != segundo.resposta["aporteId"]

    assert consultar_banco(tmp_path) == (2, 4, 2, 8000)

    def buscar_totais(conn: sqlite3.Connection) -> list[int]:
        registros = conn.execute(
            """
            SELECT payload
            FROM outbox_evento
            WHERE tipo_evento = 'campanha.total-arrecadado-atualizado'
            """
        ).fetchall()

        return [int(json.loads(registro[0])["payload"]["valorAcumulado"]) for registro in registros]

    totais = transaction(buscar_totais, "aportes", tmp_path)

    assert sorted(totais) in ([3000, 8000], [5000, 8000])


def test_falha_na_outbox_desfaz_toda_transacao(
    tmp_path: Path,
) -> None:
    """Falha no segundo evento desfaz aporte, outbox e idempotência."""

    inicializar_banco(tmp_path)

    chamadas = 0

    def adicionar_com_falha(
        conn: sqlite3.Connection,
        evento: OutboxEvent,
    ) -> None:
        nonlocal chamadas

        chamadas += 1

        if chamadas == 2:
            raise RuntimeError("Falha simulada ao registrar segundo evento na outbox")

        adicionar_evento_original(conn, evento)

    with (
        patch.object(
            processamento,
            "add",
            side_effect=adicionar_com_falha,
        ),
        pytest.raises(
            RuntimeError,
            match="Falha simulada",
        ),
    ):
        criar_aporte(tmp_path)

    assert chamadas == 2

    # Nenhum dado da transação pode permanecer no banco.
    assert consultar_banco(tmp_path) == (0, 0, 0, 0)


def test_aporte_pode_ser_confirmado_apos_rollback(
    tmp_path: Path,
) -> None:
    """Após rollback, a mesma chave pode ser utilizada novamente."""

    inicializar_banco(tmp_path)

    with (
        patch.object(
            processamento,
            "add",
            side_effect=RuntimeError("Falha temporária na outbox"),
        ),
        pytest.raises(
            RuntimeError,
            match="Falha temporária",
        ),
    ):
        criar_aporte(
            tmp_path,
            chave="chave-recuperacao",
            valor=5000,
        )

    assert consultar_banco(tmp_path) == (0, 0, 0, 0)

    # A falha terminou: a mesma requisição pode ser processada.
    resultado = criar_aporte(
        tmp_path,
        chave="chave-recuperacao",
        valor=5000,
    )

    assert resultado.status_http == 201
    assert resultado.resposta["status"] == "CONFIRMADO"

    assert consultar_banco(tmp_path) == (1, 2, 1, 5000)


def test_aporte_confirmado_cria_pendencia_custodia(
    tmp_path: Path,
) -> None:
    """Cada aporte confirmado deve gerar uma pendência de Custódia."""

    inicializar_banco(tmp_path)

    resultado = criar_aporte(tmp_path)

    def consultar(conn: sqlite3.Connection) -> tuple[str, str, str | None]:
        registro = conn.execute(
            """
            SELECT aporte_id, status, conciliado_em
            FROM aporte_custodia
            """
        ).fetchone()

        assert registro is not None
        return registro[0], registro[1], registro[2]

    aporte_id, status, conciliado_em = transaction(consultar, "aportes", tmp_path)

    assert aporte_id == resultado.resposta["aporteId"]
    assert status == "PENDENTE"
    assert conciliado_em is None
    assert consultar_banco(tmp_path) == (1, 2, 1, 5000)


def test_reenvio_nao_duplica_pendencia_custodia(
    tmp_path: Path,
) -> None:
    """Repetir a mesma chave não deve criar outra pendência."""

    inicializar_banco(tmp_path)

    primeiro = criar_aporte(tmp_path, chave="chave-custodia")
    segundo = criar_aporte(tmp_path, chave="chave-custodia")

    def contar_pendencias(conn: sqlite3.Connection) -> int:
        return int(conn.execute("SELECT COUNT(*) FROM aporte_custodia").fetchone()[0])

    quantidade = transaction(contar_pendencias, "aportes", tmp_path)

    assert primeiro == segundo
    assert quantidade == 1
    assert consultar_banco(tmp_path) == (1, 2, 1, 5000)


def test_rollback_remove_pendencia_custodia(
    tmp_path: Path,
) -> None:
    """Uma falha na outbox também desfaz a pendência de Custódia."""

    inicializar_banco(tmp_path)

    with (
        patch.object(
            processamento,
            "add",
            side_effect=RuntimeError("Falha simulada na outbox"),
        ),
        pytest.raises(RuntimeError, match="Falha simulada"),
    ):
        criar_aporte(tmp_path, chave="chave-rollback-custodia")

    def contar_pendencias(conn: sqlite3.Connection) -> int:
        return int(conn.execute("SELECT COUNT(*) FROM aporte_custodia").fetchone()[0])

    quantidade = transaction(contar_pendencias, "aportes", tmp_path)

    assert quantidade == 0
    assert consultar_banco(tmp_path) == (0, 0, 0, 0)


def test_eventos_de_aporte_validam_catalogo_oficial(
    tmp_path: Path,
) -> None:
    """Valida os dois eventos produzidos pelo processamento de aportes."""
    inicializar_banco(tmp_path)

    resultado = criar_aporte(tmp_path)

    def buscar_eventos(
        conn: sqlite3.Connection,
    ) -> list[tuple[str, str]]:
        registros = conn.execute(
            """
            SELECT tipo_evento, payload
            FROM outbox_evento
            WHERE tipo_evento IN (?, ?)
            ORDER BY rowid
            """,
            (APORTE_CONFIRMADO, TOTAL_ARRECADADO_ATUALIZADO),
        ).fetchall()

        return [(str(tipo), str(payload)) for tipo, payload in registros]

    registros = transaction(buscar_eventos, "aportes", tmp_path)

    eventos = {}

    for tipo, payload_json in registros:
        dados = json.loads(payload_json)

        # Converte o envelope interno da Outbox para o formato do catálogo.
        dados["topic"] = dados.pop("tipo")
        dados["schemaVersion"] = dados.pop("versão")
        dados["occurredAt"] = dados.pop("ocorridoEm")

        eventos[tipo] = ler_envelope(dados)

    assert set(eventos) == {
        APORTE_CONFIRMADO,
        TOTAL_ARRECADADO_ATUALIZADO,
    }

    evento_aporte = eventos[APORTE_CONFIRMADO]
    assert isinstance(evento_aporte.payload, AporteConfirmado)

    aporte = evento_aporte.payload
    assert aporte.aporte_id == resultado.resposta["aporteId"]
    assert aporte.campanha_id == "campanha-1"
    assert aporte.investidor_id == "investidor-1"
    assert aporte.valor == 5000
    assert aporte.confirmado_em.tzinfo is not None

    evento_total = eventos[TOTAL_ARRECADADO_ATUALIZADO]
    assert isinstance(evento_total.payload, TotalArrecadadoAtualizado)

    total = evento_total.payload
    assert total.campanha_id == "campanha-1"
    assert total.valor_acumulado == 5000
