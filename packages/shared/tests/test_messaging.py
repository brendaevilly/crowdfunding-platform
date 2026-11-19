"""Testes do ciclo de vida da mensageria."""

import asyncio
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

from shared.messaging import configure_messaging


@pytest.mark.anyio
async def test_servico_inicia_sem_broker(monkeypatch, tmp_path):
    """A indisponibilidade do broker não impede a inicialização."""
    import shared.messaging as messaging

    tentativas = 0

    def registrar_com_falha(**kwargs):
        nonlocal tentativas
        tentativas += 1
        raise httpx.ConnectError("Broker indisponível")

    monkeypatch.setattr(messaging, "register_subscriptions", registrar_com_falha)
    monkeypatch.setattr(messaging, "run_relay", MagicMock())

    app = FastAPI()

    configure_messaging(
        app,
        service="teste",
        service_url="http://127.0.0.1:3991",
        broker_url="http://127.0.0.1:3990",
        handlers={"IdentidadeVerificada": lambda conn, payload: None},
        data_dir=tmp_path,
    )

    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.1)
        assert tentativas >= 1


@pytest.mark.anyio
async def test_assinatura_recupera_quando_broker_volta(monkeypatch, tmp_path):
    """O registro é repetido até o broker ficar disponível."""
    import shared.messaging as messaging

    tentativas = 0
    registrado = asyncio.Event()

    def registrar_com_recuperacao(**kwargs):
        nonlocal tentativas
        tentativas += 1

        if tentativas == 1:
            raise httpx.ConnectError("Broker temporariamente indisponível")

        loop.call_soon_threadsafe(registrado.set)

    loop = asyncio.get_running_loop()

    monkeypatch.setattr(messaging, "register_subscriptions", registrar_com_recuperacao)
    monkeypatch.setattr(messaging, "run_relay", MagicMock())
    monkeypatch.setattr(messaging, "RETRY_SECONDS", 0.01)

    app = FastAPI()

    configure_messaging(
        app,
        service="teste",
        service_url="http://127.0.0.1:3991",
        broker_url="http://127.0.0.1:3990",
        handlers={"IdentidadeVerificada": lambda conn, payload: None},
        data_dir=tmp_path,
    )

    async with app.router.lifespan_context(app):
        await asyncio.wait_for(registrado.wait(), timeout=2.0)

    assert tentativas == 2
