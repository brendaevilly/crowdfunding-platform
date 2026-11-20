"""Configurações e fixtures globais de teste para o microsserviço Campanhas."""

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def desabilitar_messaging_nos_testes(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Desabilita o polling e subscriptions automáticos do broker em testes de unidade/API."""
    monkeypatch.setenv("CAMPANHAS_MESSAGING_ENABLED", "false")
    yield
