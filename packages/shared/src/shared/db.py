
"""Conexão SQLite independente para cada serviço."""

import re
import sqlite3
from contextlib import closing
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


def migrate(
    service: str,
    migrations_dir: str | Path,
    data_dir: str | Path = "data",
) -> list[int]:
    """Executa migrations pendentes em ordem de versão."""

    directory = Path(migrations_dir)

    if not directory.is_dir():
        raise FileNotFoundError(
            f"Pasta de migrations não encontrada: {directory}"
        )

    files = {}

    for path in directory.glob("*.sql"):
        match = re.fullmatch(
            r"([0-9]+)_[a-zA-Z0-9_-]+\.sql",
            path.name,
        )

        if match is None:
            raise ValueError(
                f"Nome de migration inválido: {path.name}"
            )

        version = int(match.group(1))

        if version in files:
            raise ValueError(
                f"Versão de migration duplicada: {version}"
            )

        files[version] = path

    applied_now = []

    with closing(open_db(service, data_dir)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                applied_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()

        applied = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT version, filename FROM schema_migrations"
            )
        }

        for version, path in sorted(files.items()):
            if version in applied:
                if applied[version] != path.name:
                    raise ValueError(
                        f"Versão {version} já usada por outro arquivo"
                    )
                continue

            script = path.read_text(encoding="utf-8")
            filename = path.name.replace("'", "''")

            try:
                connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + script
                    + "\nINSERT INTO schema_migrations "
                    + "(version, filename) VALUES "
                    + f"({version}, '{filename}');\n"
                    + "COMMIT;"
                )
            except Exception:
                connection.rollback()
                raise

            applied_now.append(version)

    return applied_now

