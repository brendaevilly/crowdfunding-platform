"""Testes da infraestrutura SQLite compartilhada."""

import sqlite3
from pathlib import Path

import pytest

from shared.db import migrate, open_db, transaction
from shared.money import from_cents, to_cents


def test_bancos_separados(tmp_path: Path) -> None:
    """Serviços diferentes não compartilham tabelas."""

    with open_db("identidade", tmp_path) as db:
        db.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY)")

    with open_db("campanhas", tmp_path) as db:
        tabelas = {
            row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

    assert "usuarios" not in tabelas
    assert (tmp_path / "identidade.db").exists()
    assert (tmp_path / "campanhas.db").exists()


def test_configuracoes_sqlite(tmp_path: Path) -> None:
    """WAL e chaves estrangeiras devem estar ativos."""

    with open_db("aportes", tmp_path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migration_idempotente(tmp_path: Path) -> None:
    """A mesma migration deve ser aplicada uma única vez."""

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    migration = migrations_dir / "001_criar_usuarios.sql"
    migration.write_text(
        "CREATE TABLE usuarios (id INTEGER PRIMARY KEY);",
        encoding="utf-8",
    )

    data_dir = tmp_path / "data"

    primeira = migrate("identidade", migrations_dir, data_dir)
    segunda = migrate("identidade", migrations_dir, data_dir)

    assert primeira == [1]
    assert segunda == []

    with open_db("identidade", data_dir) as db:
        quantidade = db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]

    assert quantidade == 1


def test_transaction_commit(tmp_path: Path) -> None:
    """Uma transação bem-sucedida deve salvar os dados."""

    with open_db("aportes", tmp_path) as db:
        db.execute("CREATE TABLE aportes (valor INTEGER)")

    def inserir(db: sqlite3.Connection) -> None:
        db.execute("INSERT INTO aportes (valor) VALUES (1500)")

    transaction(inserir, "aportes", tmp_path)

    with open_db("aportes", tmp_path) as db:
        quantidade = db.execute("SELECT COUNT(*) FROM aportes").fetchone()[0]

    assert quantidade == 1


def test_transaction_rollback(tmp_path: Path) -> None:
    """Uma transação com erro deve desfazer a operação."""

    with open_db("aportes", tmp_path) as db:
        db.execute("CREATE TABLE aportes (valor INTEGER)")

    def falhar(db: sqlite3.Connection) -> None:
        db.execute("INSERT INTO aportes (valor) VALUES (1500)")
        raise RuntimeError("Erro simulado")

    with pytest.raises(RuntimeError):
        transaction(falhar, "aportes", tmp_path)

    with open_db("aportes", tmp_path) as db:
        quantidade = db.execute("SELECT COUNT(*) FROM aportes").fetchone()[0]

    assert quantidade == 0


def test_valores_monetarios() -> None:
    """Valores monetários devem usar centavos inteiros."""

    assert to_cents("25.90") == 2590
    assert to_cents("10.50") == 1050
    assert to_cents("0.01") == 1
    assert str(from_cents(2590)) == "25.90"
