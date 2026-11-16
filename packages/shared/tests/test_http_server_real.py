"""Sobe um uvicorn de verdade (servidor de exemplo) e chama /health pelo ServiceClient."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

from shared.http import ServiceClient
from shared.http.example import app
from shared.http.runner import resolve_port


@pytest.fixture
def porta_servidor() -> Iterator[int]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = int(s.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=porta, log_config=None, access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    limite = time.monotonic() + 10
    while not server.started and time.monotonic() < limite:
        time.sleep(0.02)
    assert server.started, "servidor não subiu"
    try:
        yield porta
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_servidor_de_exemplo_responde_health(porta_servidor: int) -> None:
    async def _rodar() -> None:
        async with ServiceClient(base_url=f"http://127.0.0.1:{porta_servidor}") as c:
            r = await c.get("/health", headers={"x-correlation-id": "real-1"})
            assert r.status_code == 200
            assert r.json()["service"] == "exemplo"
            assert r.headers["x-correlation-id"] == "real-1"

            ok = await c.post("/eco", json={"texto": "abc"})
            assert ok.json() == {"texto": "abc", "tamanho": 3}
            ruim = await c.post("/eco", json={"texto": ""})
            assert ruim.status_code == 422
            conflito = await c.post("/eco", json={"texto": "erro"})
            assert conflito.status_code == 409

    asyncio.run(_rodar())


def test_resolve_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    assert resolve_port("x", 1234) == 1234
    monkeypatch.setenv("PORT", "4321")
    assert resolve_port("x") == 4321
