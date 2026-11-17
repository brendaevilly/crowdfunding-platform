"""Entrada do processo: `python -m gateway.main` (porta de services.json)."""

from __future__ import annotations

from gateway.app import NOME, criar_app
from shared.http import run


def main() -> None:
    run(criar_app(), NOME)


if __name__ == "__main__":
    main()
