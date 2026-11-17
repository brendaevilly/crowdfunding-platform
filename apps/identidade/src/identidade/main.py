"""Ponto de entrada do serviço Identidade: `python -m identidade.main`."""

from __future__ import annotations

from identidade.app import app
from shared.http import run


def main() -> None:
    run(app, "identidade")


if __name__ == "__main__":
    main()
