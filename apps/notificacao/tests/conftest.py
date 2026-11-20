"""Configurações e fixtures globais de teste para o microsserviço Notificação."""

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def desabilitar_messaging_nos_testes(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Desabilita o polling e subscriptions automáticos do broker e TTL em testes."""
    monkeypatch.setenv("NOTIFICACAO_MESSAGING_ENABLED", "false")
    monkeypatch.setenv("NOTIFICACAO_TTL_ENABLED", "false")
    yield
