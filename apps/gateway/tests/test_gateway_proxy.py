from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.app import criar_app
from gateway.config import GatewaySettings
from shared.auth import emitir_token

SEGREDO = "segredo-de-teste"
AGORA = 1_800_000_000.0
SERVICOS = {
    "gateway": "http://gateway.test",
    "broker": "http://broker.test",
    "identidade": "http://identidade.test",
    "campanhas": "http://campanhas.test",
    "aportes": "http://aportes.test",
    "custodia_retornos": "http://custodia.test",
    "notificacao": "http://notificacao.test",
}


class Upstream:
    """Transporte httpx simulado: registra as requisições e responde por host."""

    def __init__(self) -> None:
        self.recebidas: list[httpx.Request] = []
        self.fora: set[str] = set()
        self.lentos: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.recebidas.append(request)
        host = request.url.host.removesuffix(".test")
        if host in self.fora:
            raise httpx.ConnectError("recusada", request=request)
        if host in self.lentos:
            raise httpx.ReadTimeout("lento", request=request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path.endswith("/nao-existe"):
            return httpx.Response(404, json={"error": {"code": "nao_encontrado"}})
        return httpx.Response(
            201,
            json={"host": host, "path": request.url.path, "query": request.url.query.decode()},
            headers={"x-do-servico": "sim", "set-cookie": "a=b", "x-correlation-id": "do-servico"},
        )


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


def _cliente(upstream: Upstream, **cfg: Any) -> TestClient:
    settings = GatewaySettings(jwt_secret=SEGREDO, **cfg)
    app = criar_app(
        settings=settings,
        servicos=SERVICOS,
        transport=httpx.MockTransport(upstream),
        agora=lambda: AGORA,
        relogio=lambda: 0.0,
    )
    return TestClient(app)


@pytest.fixture
def client(upstream: Upstream) -> TestClient:
    return _cliente(upstream, rate_limit_requests=1000)


def _auth(user: str = "u1", perfil: str = "INVESTIDOR", **kw: Any) -> dict[str, str]:
    return {
        "authorization": f"Bearer {emitir_token(user, perfil, segredo=SEGREDO, agora=AGORA, **kw)}"
    }


def _ultima(upstream: Upstream) -> httpx.Request:
    return upstream.recebidas[-1]


# ----------------------------------------------------------------------------- autenticação


def test_sem_token_em_rota_protegida_retorna_401(client: TestClient, upstream: Upstream) -> None:
    r = client.get("/api/campanhas/c1/status")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.json()["error"]["code"] == "nao_autenticado"
    assert upstream.recebidas == [], "nada deve chegar ao serviço sem autenticação"


@pytest.mark.parametrize(
    "cabecalho",
    [
        "Bearer lixo",
        "Bearer",
        "Basic dXNlcjpwYXNz",
        "token-sem-esquema",
    ],
)
def test_token_invalido_retorna_401(client: TestClient, upstream: Upstream, cabecalho: str) -> None:
    r = client.get("/api/aportes", headers={"authorization": cabecalho})
    assert r.status_code == 401
    assert upstream.recebidas == []


def test_token_assinado_com_outro_segredo(client: TestClient) -> None:
    token = emitir_token("u1", "INVESTIDOR", segredo="outro", agora=AGORA)
    r = client.get("/api/aportes", headers={"authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "token_invalido"


def test_token_expirado(client: TestClient) -> None:
    r = client.get("/api/aportes", headers=_auth(expira_em_segundos=-1))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "token_expirado"


def test_perfil_desconhecido_e_recusado(client: TestClient) -> None:
    r = client.get("/api/aportes", headers=_auth(perfil="ADMIN"))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "token_invalido"


@pytest.mark.parametrize("caminho", ["/api/identidade/usuarios", "/api/identidade/login"])
def test_cadastro_e_login_sao_publicos(
    client: TestClient, upstream: Upstream, caminho: str
) -> None:
    r = client.post(caminho, json={"email": "a@b.c"})
    assert r.status_code == 201
    assert _ultima(upstream).url.host == "identidade.test"
    assert "x-user-id" not in _ultima(upstream).headers


def test_rota_publica_so_vale_para_o_metodo_certo(client: TestClient) -> None:
    assert client.get("/api/identidade/usuarios").status_code == 401


# ----------------------------------------------------------------------------- proxy


def test_injeta_identidade_e_nao_repassa_o_token(client: TestClient, upstream: Upstream) -> None:
    r = client.get("/api/campanhas/c1/status?detalhe=1", headers=_auth("u42", "EMPREENDEDOR"))
    assert r.status_code == 201
    req = _ultima(upstream)
    assert req.url.host == "campanhas.test"
    assert (req.url.path, req.url.query) == ("/campanhas/c1/status", b"detalhe=1")
    assert req.headers["x-user-id"] == "u42"
    assert req.headers["x-user-perfil"] == "EMPREENDEDOR"
    assert "authorization" not in req.headers


def test_x_user_enviado_pelo_cliente_e_sobrescrito(client: TestClient, upstream: Upstream) -> None:
    client.get(
        "/api/aportes", headers={**_auth("real"), "x-user-id": "admin", "x-user-perfil": "ROOT"}
    )
    req = _ultima(upstream)
    assert req.headers.get_list("x-user-id") == ["real"]
    assert req.headers.get_list("x-user-perfil") == ["INVESTIDOR"]


def test_x_user_forjado_em_rota_publica_e_removido(client: TestClient, upstream: Upstream) -> None:
    client.post("/api/identidade/login", headers={"x-user-id": "admin"}, json={})
    assert "x-user-id" not in _ultima(upstream).headers


def test_metodo_corpo_e_headers_do_cliente_chegam_ao_servico(
    client: TestClient, upstream: Upstream
) -> None:
    r = client.post(
        "/api/aportes",
        headers={**_auth(), "idempotency-key": "k-1", "content-type": "application/json"},
        content=json.dumps({"valor": 500}),
    )
    assert r.status_code == 201
    req = _ultima(upstream)
    assert req.method == "POST"
    assert req.url.path == "/aportes"
    assert req.headers["idempotency-key"] == "k-1"
    assert json.loads(req.content) == {"valor": 500}


@pytest.mark.parametrize(
    ("prefixo", "host"),
    [
        ("identidade", "identidade"),
        ("campanhas", "campanhas"),
        ("aportes", "aportes"),
        ("retornos", "custodia"),
        ("notificacoes", "notificacao"),
    ],
)
def test_cada_prefixo_vai_para_o_servico_certo(
    client: TestClient, upstream: Upstream, prefixo: str, host: str
) -> None:
    client.get(f"/api/{prefixo}/x", headers=_auth())
    assert _ultima(upstream).url.host == f"{host}.test"


def test_resposta_do_servico_e_repassada(client: TestClient) -> None:
    r = client.get("/api/campanhas/c1", headers=_auth())
    assert r.status_code == 201
    assert r.json()["path"] == "/campanhas/c1"
    assert r.headers["x-do-servico"] == "sim"


def test_erro_do_servico_e_repassado_sem_alteracao(client: TestClient) -> None:
    r = client.get("/api/campanhas/nao-existe", headers=_auth())
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "nao_encontrado"}}


def test_prefixo_desconhecido_e_404(client: TestClient, upstream: Upstream) -> None:
    r = client.get("/api/xyz/1", headers=_auth())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "rota_desconhecida"
    assert upstream.recebidas == []


def test_corpo_grande_demais(client: TestClient) -> None:
    r = client.post("/api/aportes", headers=_auth(), content=b"x" * 1_048_577)
    assert r.status_code == 413


# ----------------------------------------------------------------------------- correlation-id


def test_gera_correlation_id_e_propaga_ao_servico(client: TestClient, upstream: Upstream) -> None:
    r = client.get("/api/aportes", headers=_auth())
    gerado = r.headers["x-correlation-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", gerado)
    assert _ultima(upstream).headers["x-correlation-id"] == gerado


def test_respeita_correlation_id_do_cliente(client: TestClient, upstream: Upstream) -> None:
    r = client.get("/api/aportes", headers={**_auth(), "x-correlation-id": "cli-1"})
    assert r.headers["x-correlation-id"] == "cli-1"
    assert _ultima(upstream).headers["x-correlation-id"] == "cli-1"


def test_correlation_id_aparece_nos_erros(client: TestClient) -> None:
    r = client.get("/api/aportes", headers={"x-correlation-id": "cli-2"})
    assert r.json()["error"]["correlationId"] == "cli-2"


# ----------------------------------------------------------------------------- serviço fora


def test_servico_fora_retorna_503_e_o_gateway_continua(
    client: TestClient, upstream: Upstream
) -> None:
    upstream.fora.add("campanhas")
    r = client.get("/api/campanhas/c1/status", headers=_auth())
    assert r.status_code == 503
    erro = r.json()["error"]
    assert erro["code"] == "servico_indisponivel"
    assert erro["details"] == {"servico": "campanhas"}
    assert "campanhas" in erro["message"]
    # outros serviços e o próprio gateway seguem respondendo
    assert client.get("/api/aportes", headers=_auth()).status_code == 201
    assert client.get("/health").status_code == 200
    # e quando o serviço volta, volta a funcionar
    upstream.fora.clear()
    assert client.get("/api/campanhas/c1/status", headers=_auth()).status_code == 201


def test_servico_lento_retorna_504(client: TestClient, upstream: Upstream) -> None:
    upstream.lentos.add("aportes")
    r = client.get("/api/aportes", headers=_auth())
    assert r.status_code == 504
    assert r.json()["error"]["code"] == "servico_timeout"


# ----------------------------------------------------------------------------- rate limit


def test_rate_limit_por_usuario(upstream: Upstream) -> None:
    client = _cliente(upstream, rate_limit_requests=2, rate_limit_window=60)
    assert client.get("/api/aportes", headers=_auth("u1")).status_code == 201
    assert client.get("/api/aportes", headers=_auth("u1")).status_code == 201
    r = client.get("/api/aportes", headers=_auth("u1"))
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "limite_excedido"
    assert int(r.headers["retry-after"]) >= 1
    assert client.get("/api/aportes", headers=_auth("u2")).status_code == 201


def test_rate_limit_por_ip_sem_token_inclui_tentativas_invalidas(upstream: Upstream) -> None:
    client = _cliente(upstream, rate_limit_requests=2, rate_limit_window=60)
    assert client.get("/api/aportes").status_code == 401
    assert client.get("/api/aportes", headers={"authorization": "Bearer x"}).status_code == 401
    assert client.get("/api/aportes").status_code == 429


def test_rate_limit_protege_login(upstream: Upstream) -> None:
    client = _cliente(upstream, rate_limit_requests=2, rate_limit_window=60)
    codigos = [client.post("/api/identidade/login", json={}).status_code for _ in range(3)]
    assert codigos == [201, 201, 429]


# ----------------------------------------------------------------------------- /health agregado


def test_health_agregado_tudo_no_ar(client: TestClient) -> None:
    corpo = client.get("/health").json()
    assert corpo["status"] == "ok"
    assert corpo["service"] == "gateway"
    assert set(corpo["dependencies"]) == set(SERVICOS) - {"gateway"}
    assert all(d["status"] == "up" for d in corpo["dependencies"].values())


def test_health_agregado_com_servico_fora(client: TestClient, upstream: Upstream) -> None:
    upstream.fora.add("notificacao")
    r = client.get("/health")
    assert r.status_code == 200  # o gateway está vivo; o estado vai no corpo
    corpo = r.json()
    assert corpo["status"] == "degraded"
    assert corpo["dependencies"]["notificacao"]["status"] == "down"
    assert corpo["dependencies"]["campanhas"]["status"] == "up"
