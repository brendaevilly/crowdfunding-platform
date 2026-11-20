"""Testes de circuitos e observabilidade agregada no /health do Gateway."""

import httpx
from fastapi.testclient import TestClient

from gateway.app import criar_app
from gateway.config import GatewaySettings


class UpstreamComCircuitos(httpx.AsyncBaseTransport):
    """Transport de teste simulando upstreams e seus endpoints /health com circuitos."""

    def __init__(self) -> None:
        self.falhar = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)

        if url.endswith("/health"):
            if self.falhar:
                raise httpx.ConnectError("Serviço indisponível", request=request)

            corpo = {
                "status": "ok",
                "service": "aportes",
                "version": "0.1.0",
                "circuit_breakers": {
                    "campanhas": {
                        "state": "closed",
                        "failure_count": 0,
                        "failure_threshold": 3,
                    }
                },
            }
            return httpx.Response(200, json=corpo)

        if self.falhar:
            raise httpx.ConnectError("Falha de conexão", request=request)

        return httpx.Response(200, json={"ok": True})


def test_health_gateway_exibe_circuitos_agregados() -> None:
    transport = UpstreamComCircuitos()
    servicos = {
        "aportes": "http://aportes.test",
        "campanhas": "http://campanhas.test",
    }

    app = criar_app(
        settings=GatewaySettings(jwt_secret="segredo-teste"),
        servicos=servicos,
        transport=transport,
    )

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        dados = resp.json()

        assert dados["status"] == "ok"
        assert "dependencies" in dados
        assert "aportes" in dados["dependencies"]
        assert "campanhas" in dados["dependencies"]

        # Verifica circuitos na dependência
        dep_aportes = dados["dependencies"]["aportes"]
        assert dep_aportes["status"] == "up"
        assert "circuits" in dep_aportes
        assert "campanhas" in dep_aportes["circuits"]
        assert dep_aportes["circuits"]["campanhas"]["state"] == "closed"

        # Verifica circuitos agregados na raiz
        assert "circuits" in dados
        assert "aportes" in dados["circuits"]


def test_health_gateway_com_circuito_aberto() -> None:
    transport = UpstreamComCircuitos()
    servicos = {
        "aportes": "http://aportes.test",
    }

    app = criar_app(
        settings=GatewaySettings(jwt_secret="segredo-teste"),
        servicos=servicos,
        transport=transport,
    )

    with TestClient(app) as client:
        # Força falhas consecutivas
        transport.falhar = True

        for _ in range(5):
            client.get("/api/aportes", headers={"Authorization": "Bearer invalido"})
            # 401 ou 503

        # O /health reflete estado down ou circuito
        resp = client.get("/health")
        assert resp.status_code == 200
        dados = resp.json()
        assert dados["status"] == "degraded"
        assert dados["dependencies"]["aportes"]["status"] == "down"
