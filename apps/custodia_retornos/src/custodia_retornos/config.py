"""Configurações e URLs do serviço de Custódia."""

from __future__ import annotations

import os

from shared.config import service_url


def custodia_url_padrao() -> str:
    """URL base do serviço de Custódia."""
    return os.getenv(
        "CUSTODIA_RETORNOS_URL",
        service_url("custodia_retornos"),
    )


def broker_url_padrao() -> str:
    """URL base do broker de eventos."""
    return os.getenv("BROKER_URL", service_url("broker"))


def percentual_taxa_padrao() -> str:
    """Retorna o percentual de taxa configurado para a plataforma."""
    return os.getenv("CUSTODIA_TAXA_PERCENTUAL", "0")
