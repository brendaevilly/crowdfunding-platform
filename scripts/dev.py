#!/usr/bin/env python3
"""Placeholder de `make dev` (a orquestração real é a issue F07).

Por enquanto só lista os serviços definidos em services.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def main(argv: list[str]) -> int:
    servicos: dict[str, dict[str, object]] = json.loads(
        (RAIZ / "services.json").read_text(encoding="utf-8")
    )
    print("make dev ainda é um placeholder (issue F07). Serviços planejados:")
    for nome, info in servicos.items():
        print(f"  {nome:<18} {info['url']}")
    if argv[1:2] == ["up"]:
        print("A orquestração (subir/derrubar processos) ainda não foi implementada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
