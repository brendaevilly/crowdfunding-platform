"""Configurações e URLs do serviço Campanhas."""

from __future__ import annotations

import os

from shared.config import service_url


def campanhas_url_padrao() -> str:
    """URL base do serviço Campanhas."""
    return os.getenv("CAMPANHAS_URL", service_url("campanhas"))


def broker_url_padrao() -> str:
    """URL base do broker de eventos."""
    return os.getenv("BROKER_URL", service_url("broker"))
