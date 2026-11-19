"""Configurações do serviço Identidade."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _ler_services_json() -> dict[str, dict[str, str | int]]:
    raiz = Path(__file__).resolve().parents[4]
    arquivo = raiz / "services.json"
    if arquivo.is_file():
        try:
            dados: dict[str, dict[str, str | int]] = json.loads(arquivo.read_text(encoding="utf-8"))
            return dados
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def broker_url_padrao() -> str:
    """URL do broker local."""
    env = os.getenv("BROKER_URL")
    if env:
        return env.rstrip("/")
    servicos = _ler_services_json()
    return str(servicos.get("broker", {}).get("url", "http://127.0.0.1:3010")).rstrip("/")


def identidade_url_padrao() -> str:
    """URL do próprio serviço Identidade."""
    env = os.getenv("IDENTIDADE_URL")
    if env:
        return env.rstrip("/")
    servicos = _ler_services_json()
    return str(servicos.get("identidade", {}).get("url", "http://127.0.0.1:3001")).rstrip("/")
