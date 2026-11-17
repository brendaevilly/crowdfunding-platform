"""Testes da outbox transacional."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from shared.db import transaction
from shared.messaging_schema import install_messaging_schema
from shared.outbox import OutboxEvent, add


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Cria banco temporário para cada teste."""
    install_messaging_schema("campanhas", tmp_path)
    return tmp_path


def test_outbox_registra_evento_na_transacao(data_dir: Path) -> None:
    """Evento é salvo junto com a operação de negócio."""

    def salvar(conn: sqlite3.Connection) -> str:
        conn.execute("CREATE TABLE IF NOT EXISTS campanhas_teste (id TEXT PRIMARY KEY)")
        conn.execute(
            "INSERT INTO campanhas_teste (id) VALUES (?)",
            ("campanha-1",),
        )

        return add(
            conn,
            OutboxEvent(
                agregado_id="campanha-1",
                tipo_evento="CampanhaPublicada",
                payload={"campanhaId": "campanha-1"},
                correlation_id="correlation-1",
            ),
        )

    event_id = transaction(salvar, "campanhas", data_dir)

    def consultar(conn: sqlite3.Connection) -> tuple[Any, ...] | None:
        row: tuple[Any, ...] | None = conn.execute(
            """
            SELECT agregado_id, tipo_evento, payload, status
            FROM outbox_evento
            WHERE outbox_id = ?
            """,
            (event_id,),
        ).fetchone()
        return row

    row = transaction(consultar, "campanhas", data_dir)

    assert row is not None
    assert row[0] == "campanha-1"
    assert row[1] == "CampanhaPublicada"
    assert row[3] == "PENDENTE"

    envelope: dict[str, Any] = json.loads(row[2])
    assert envelope["eventId"] == event_id
    assert envelope["tipo"] == "CampanhaPublicada"
    assert envelope["payload"]["campanhaId"] == "campanha-1"


def test_outbox_rollback_desfaz_evento(data_dir: Path) -> None:
    """Falha na operação desfaz também o registro na outbox."""

    def salvar_com_erro(conn: sqlite3.Connection) -> None:
        add(
            conn,
            OutboxEvent(
                agregado_id="campanha-2",
                tipo_evento="CampanhaPublicada",
                payload={"campanhaId": "campanha-2"},
                correlation_id="correlation-2",
            ),
        )

        raise RuntimeError("Falha simulada")

    with pytest.raises(RuntimeError, match="Falha simulada"):
        transaction(salvar_com_erro, "campanhas", data_dir)

    def contar(conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COUNT(*) FROM outbox_evento").fetchone()
        assert row is not None
        return int(row[0])

    assert transaction(contar, "campanhas", data_dir) == 0


def test_messaging_migrations_sao_idempotentes(tmp_path: Path) -> None:
    """Aplicar migrations novamente não duplica registros."""
    primeira = install_messaging_schema("aportes", tmp_path)
    segunda = install_messaging_schema("aportes", tmp_path)

    assert primeira == [1, 2]
    assert segunda == []

    def contar(conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COUNT(*) FROM messaging_schema_migrations").fetchone()
        assert row is not None
        return int(row[0])

    assert transaction(contar, "aportes", tmp_path) == 2
