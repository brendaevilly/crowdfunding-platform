"""Configurações e URLs do serviço Notificação."""

from __future__ import annotations

import os

from shared.config import service_url


def notificacao_url_padrao() -> str:
    """URL base do serviço Notificação."""
    return os.getenv("NOTIFICACAO_URL", service_url("notificacao"))


def broker_url_padrao() -> str:
    """URL base do broker de eventos."""
    return os.getenv("BROKER_URL", service_url("broker"))
