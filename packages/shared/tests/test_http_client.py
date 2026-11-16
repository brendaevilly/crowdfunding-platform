from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from shared.correlation import reset_correlation_id, set_correlation_id
from shared.http import ServiceClient


def _transporte(capturadas: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        capturadas.append(request)
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handler)


def _executar(client: ServiceClient, cid: str | None, **kw: object) -> httpx.Response:
    async def _rodar() -> httpx.Response:
        token = set_correlation_id(cid) if cid else None
        try:
            async with client:
                return await client.get("/x", **kw)
        finally:
            if token is not None:
                reset_correlation_id(token)

    return asyncio.run(_rodar())


def test_propaga_correlation_id_atual() -> None:
    reqs: list[httpx.Request] = []
    c = ServiceClient(base_url="http://svc", transport=_transporte(reqs))
    assert _executar(c, "cid-7").json() == {"ok": True}
    assert reqs[0].headers["x-correlation-id"] == "cid-7"
    assert str(reqs[0].url) == "http://svc/x"


def test_sem_contexto_nao_inventa_header() -> None:
    reqs: list[httpx.Request] = []
    c = ServiceClient(base_url="http://svc", transport=_transporte(reqs))
    _executar(c, None)
    assert "x-correlation-id" not in reqs[0].headers


def test_header_explicito_tem_prioridade() -> None:
    reqs: list[httpx.Request] = []
    c = ServiceClient(base_url="http://svc", transport=_transporte(reqs))
    _executar(c, "do-contexto", headers={"x-correlation-id": "explicito"})
    assert reqs[0].headers["x-correlation-id"] == "explicito"


def test_metodos_http() -> None:
    reqs: list[httpx.Request] = []

    async def _rodar() -> None:
        async with ServiceClient(base_url="http://svc", transport=_transporte(reqs)) as c:
            await c.post("/a", json={"k": 1})
            await c.put("/a")
            await c.patch("/a")
            await c.delete("/a")

    asyncio.run(_rodar())
    assert [r.method for r in reqs] == ["POST", "PUT", "PATCH", "DELETE"]
    assert json.loads(reqs[0].content) == {"k": 1}


def test_resolve_url_pelo_services_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arq = tmp_path / "services.json"
    arq.write_text(json.dumps({"campanhas": {"url": "http://h:3002", "port": 3002}}), "utf-8")
    monkeypatch.setenv("SERVICES_FILE", str(arq))
    reqs: list[httpx.Request] = []
    _executar(ServiceClient("campanhas", transport=_transporte(reqs)), None)
    assert str(reqs[0].url) == "http://h:3002/x"


def test_timeout_configuravel(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ServiceClient(base_url="http://svc", timeout=1.5).timeout == 1.5
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "7")
    assert ServiceClient(base_url="http://svc").timeout == 7.0
    monkeypatch.delenv("HTTP_TIMEOUT_SECONDS")
    assert ServiceClient(base_url="http://svc").timeout == 5.0


def test_timeout_estoura_como_erro_do_httpx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=request)

    c = ServiceClient(base_url="http://svc", transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.ReadTimeout):
        _executar(c, None)


def test_exige_exatamente_service_ou_base_url() -> None:
    with pytest.raises(ValueError):
        ServiceClient()
    with pytest.raises(ValueError):
        ServiceClient("a", base_url="http://x")
