"""Configurações e fixtures globais de teste para o microsserviço Notificação."""

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def desabilitar_messaging_nos_testes(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Desabilita o polling e subscriptions automáticos do broker em testes de unidade/API."""
    monkeypatch.setenv("NOTIFICACAO_MESSAGING_ENABLED", "false")
    yield
