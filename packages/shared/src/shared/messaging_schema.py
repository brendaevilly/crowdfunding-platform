"""Instalação das tabelas compartilhadas de messaging."""

import re
from contextlib import closing
from pathlib import Path

from shared.db import open_db

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def install_messaging_schema(
    service: str,
    data_dir: str | Path = "data",
) -> list[int]:
    """Aplica migrations de messaging no banco de um serviço."""
    if not MIGRATIONS_DIR.is_dir():
        raise FileNotFoundError(f"Migrations de messaging não encontradas: {MIGRATIONS_DIR}")

    files: dict[int, Path] = {}

    for path in MIGRATIONS_DIR.glob("*.sql"):
        match = re.fullmatch(
            r"([0-9]+)_[a-zA-Z0-9_-]+\.sql",
            path.name,
        )
        if match is None:
            raise ValueError(f"Migration inválida: {path.name}")

        version = int(match.group(1))

        if version in files:
            raise ValueError(f"Versão duplicada: {version}")

        files[version] = path

    applied_now: list[int] = []

    with closing(open_db(service, data_dir)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messaging_schema_migrations (
                version INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()

        applied = dict(
            conn.execute(
                """
                SELECT version, filename
                FROM messaging_schema_migrations
                """
            ).fetchall()
        )

        for version, path in sorted(files.items()):
            if version in applied:
                if applied[version] != path.name:
                    raise ValueError(f"Versão {version} já usada por outro arquivo")
                continue

            script = path.read_text(encoding="utf-8")
            filename = path.name.replace("'", "''")

            try:
                conn.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + script
                    + "\nINSERT INTO messaging_schema_migrations "
                    + "(version, filename) VALUES "
                    + f"({version}, '{filename}');\n"
                    + "COMMIT;"
                )
            except Exception:
                conn.rollback()
                raise

            applied_now.append(version)

    return applied_now
