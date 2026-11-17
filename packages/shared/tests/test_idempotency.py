"""Testes do consumo idempotente de eventos."""

import sqlite3
from functools import partial

import pytest

from shared.db import transaction
from shared.idempotency import consume_once
from shared.messaging_schema import install_messaging_schema


@pytest.fixture
def data_dir(tmp_path):
    """Prepara o banco temporário para cada teste."""
    install_messaging_schema("aportes", tmp_path)

    def criar_tabela(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE efeitos_teste (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evento_id TEXT NOT NULL
            )
            """
        )

    transaction(criar_tabela, "aportes", tmp_path)
    return tmp_path


def registrar_efeito(
    conn: sqlite3.Connection,
    evento_id: str,
) -> None:
    """Simula um efeito de negócio."""
    conn.execute(
        "INSERT INTO efeitos_teste (evento_id) VALUES (?)",
        (evento_id,),
    )


def contar_efeitos(data_dir) -> int:
    """Conta quantos efeitos foram persistidos."""

    def contar(conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COUNT(*) FROM efeitos_teste").fetchone()
        return row[0]

    return transaction(contar, "aportes", data_dir)


def test_tres_entregas_produzem_um_efeito(data_dir):
    """Três entregas do mesmo evento geram um único efeito."""
    resultados = []

    for _ in range(3):

        def processar(conn: sqlite3.Connection):
            return consume_once(
                "evento-123",
                conn,
                lambda tx: registrar_efeito(tx, "evento-123"),
            )

        resultados.append(transaction(processar, "aportes", data_dir))

    assert resultados == [
        (True, None),
        (False, None),
        (False, None),
    ]
    assert contar_efeitos(data_dir) == 1


def processar_evento(
    conn: sqlite3.Connection,
    evento_id: str,
):
    """Processa um evento com sua chave de idempotência."""
    return consume_once(
        evento_id,
        conn,
        partial(registrar_efeito, evento_id=evento_id),
    )


def test_eventos_diferentes_sao_processados(data_dir):
    """Eventos distintos podem produzir efeitos distintos."""
    for evento_id in ("evento-1", "evento-2"):
        transaction(
            partial(processar_evento, evento_id=evento_id),
            "aportes",
            data_dir,
        )

    assert contar_efeitos(data_dir) == 2


def test_falha_desfaz_chave_e_efeito(data_dir):
    """Uma falha permite processar o evento novamente."""

    def processar_com_falha(conn: sqlite3.Connection):
        def efeito(tx: sqlite3.Connection):
            registrar_efeito(tx, "evento-falha")
            raise RuntimeError("Falha simulada")

        return consume_once("evento-falha", conn, efeito)

    with pytest.raises(RuntimeError, match="Falha simulada"):
        transaction(processar_com_falha, "aportes", data_dir)

    assert contar_efeitos(data_dir) == 0

    def tentar_novamente(conn: sqlite3.Connection):
        return consume_once(
            "evento-falha",
            conn,
            lambda tx: registrar_efeito(tx, "evento-falha"),
        )

    processed, _ = transaction(
        tentar_novamente,
        "aportes",
        data_dir,
    )

    assert processed is True
    assert contar_efeitos(data_dir) == 1


def test_chave_vazia_e_rejeitada(data_dir):
    """Chaves de idempotência vazias não são permitidas."""

    def processar(conn: sqlite3.Connection):
        return consume_once("", conn, lambda tx: None)

    with pytest.raises(
        ValueError,
        match="A chave de idempotência não pode ser vazia",
    ):
        transaction(processar, "aportes", data_dir)
