
"""Conexão SQLite independente para cada serviço."""

import re
import sqlite3
from pathlib import Path


def open_db(
    service: str,
    data_dir: str | Path = "data",
) -> sqlite3.Connection:
    """Abre o banco SQLite exclusivo de um serviço."""

    if not re.fullmatch(r"[a-z][a-z0-9_]*", service):
        raise ValueError("Nome de serviço inválido")

    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)

    db_path = directory / f"{service}.db"

    connection = sqlite3.connect(db_path)

    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
    except Exception:
        connection.close()
        raise
