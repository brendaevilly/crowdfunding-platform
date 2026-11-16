"""Serviço mínimo (só /health) usado pelo launcher enquanto um app não tem `main.py`.

Uso: `python -m shared.http.placeholder <nome-do-servico>`
"""

from __future__ import annotations

import sys

from shared.http.app import create_app
from shared.http.runner import run


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: python -m shared.http.placeholder <servico>", file=sys.stderr)
        return 2
    nome = argv[1]
    run(create_app(nome), nome)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
