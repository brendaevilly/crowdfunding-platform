"""Gateway e serviço de destino em servidores uvicorn reais (sem simulação de transporte)."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import uvicorn
from fastapi import FastAPI, Request

from gateway.app import criar_app
from gateway.config import GatewaySettings
from shared.auth import emitir_token
from shared.http import ServiceClient, create_app

SEGREDO = "segredo-de-integracao"


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Servidor:
    def __init__(self, app: FastAPI, porta: int) -> None:
        self.porta = porta
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=porta, log_config=None, access_log=False)
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def iniciar(self) -> None:
        self.thread.start()
        limite = time.monotonic() + 10
        while not self.server.started and time.monotonic() < limite:
            time.sleep(0.02)
        assert self.server.started, "servidor não subiu"

    def parar(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def _campanhas() -> FastAPI:
    app = create_app("campanhas", configure_logs=False)

    @app.get("/campanhas/{campanha_id}/status")
    async def status(campanha_id: str, request: Request) -> dict[str, str | None]:
        return {
            "campanhaId": campanha_id,
            "usuario": request.headers.get("x-user-id"),
            "perfil": request.headers.get("x-user-perfil"),
        }

    return app


@dataclass
class Ambiente:
    gateway: Servidor
    campanhas: Servidor

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.gateway.porta}"


@pytest.fixture
def ambiente() -> Iterator[Ambiente]:
    campanhas = Servidor(_campanhas(), _porta_livre())
    campanhas.iniciar()
    gateway = Servidor(
        criar_app(
            settings=GatewaySettings(jwt_secret=SEGREDO, rate_limit_requests=1000),
            servicos={
                "campanhas": f"http://127.0.0.1:{campanhas.porta}",
                "aportes": f"http://127.0.0.1:{_porta_livre()}",  # nunca sobe
            },
        ),
        _porta_livre(),
    )
    gateway.iniciar()
    try:
        yield Ambiente(gateway, campanhas)
    finally:
        gateway.parar()
        if campanhas.thread.is_alive():
            campanhas.parar()


def _token(user: str = "u7") -> dict[str, str]:
    return {"authorization": f"Bearer {emitir_token(user, 'INVESTIDOR', segredo=SEGREDO)}"}


def test_sem_token_401_e_com_token_chega_ao_servico_com_identidade(ambiente: Ambiente) -> None:
    async def _rodar() -> None:
        async with ServiceClient(base_url=ambiente.url) as c:
            sem = await c.get("/api/campanhas/c1/status")
            assert sem.status_code == 401

            ok = await c.get("/api/campanhas/c1/status", headers=_token("u7"))
            assert ok.status_code == 200
            assert ok.json() == {"campanhaId": "c1", "usuario": "u7", "perfil": "INVESTIDOR"}

    asyncio.run(_rodar())


def test_servico_derrubado_retorna_503_sem_derrubar_o_gateway(ambiente: Ambiente) -> None:
    async def _rodar() -> None:
        async with ServiceClient(base_url=ambiente.url) as c:
            assert (await c.get("/api/campanhas/c1/status", headers=_token())).status_code == 200

            ambiente.campanhas.parar()  # derruba o serviço de destino

            r = await c.get("/api/campanhas/c1/status", headers=_token())
            assert r.status_code == 503
            assert r.json()["error"]["code"] == "servico_indisponivel"

            # serviço que nunca existiu também dá 503; o gateway segue de pé
            assert (await c.get("/api/aportes", headers=_token())).status_code == 503
            saude = await c.get("/health")
            assert saude.status_code == 200
            corpo = saude.json()
            assert corpo["status"] == "degraded"
            assert corpo["dependencies"]["campanhas"]["status"] == "down"

    asyncio.run(_rodar())
