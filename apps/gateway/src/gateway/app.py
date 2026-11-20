"""API Gateway: ponto único de entrada (:3000).

Proxy `/api/<prefixo>/*` -> serviço (services.json), JWT + x-user-id/x-user-perfil,
rate limit por usuário/IP, correlation-id e /health agregado.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

from contracts import Perfil
from gateway.config import GatewaySettings
from gateway.proxy import headers_para_cliente, headers_para_servico
from gateway.ratelimit import LimitadorTaxa
from gateway.rotas import CaminhoInvalido, resolver, rota_publica
from shared.auth import Claims, TokenInvalido, validar_token
from shared.config import load_services
from shared.http import (
    ERROS_DE_CONEXAO,
    ERROS_DE_TIMEOUT,
    AppError,
    ServiceClient,
    create_app,
)

log = logging.getLogger("gateway")

NOME = "gateway"
VERSAO = "0.1.0"
TAMANHO_MAXIMO_CORPO = 1_048_576  # 1 MiB
METODOS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


class DependenciaSaude(BaseModel):
    status: str  # up | down
    latencyMs: float | None = None  # noqa: N815
    erro: str | None = None


class GatewayHealth(BaseModel):
    status: str  # ok | degraded
    service: str
    version: str
    dependencies: dict[str, DependenciaSaude]


def _ip(request: Request) -> str:
    return request.client.host if request.client else "desconhecido"


def _bearer(request: Request) -> str | None:
    """Extrai o token JWT do cabeçalho Authorization."""
    valor = request.headers.get("authorization", "")
    esquema, _, token = valor.partition(" ")

    return token.strip() if esquema.lower() == "bearer" and token.strip() else None


def criar_app(
    *,
    settings: GatewaySettings | None = None,
    servicos: Mapping[str, str] | None = None,
    transport: Any = None,
    relogio: Callable[[], float] = time.monotonic,
    agora: Callable[[], float] = time.time,
) -> FastAPI:
    """Cria o Gateway com proxy, autenticação e rate limit."""
    cfg = settings or GatewaySettings.from_env()

    urls = (
        dict(servicos)
        if servicos is not None
        else {nome: info.url for nome, info in load_services().items()}
    )

    limitador = LimitadorTaxa(
        cfg.rate_limit_requests,
        cfg.rate_limit_window,
        relogio,
    )

    clientes: dict[str, ServiceClient] = {}

    def cliente(nome: str) -> ServiceClient:
        if nome not in clientes:
            clientes[nome] = ServiceClient(
                base_url=urls[nome],
                timeout=cfg.upstream_timeout,
                transport=transport,
            )

        return clientes[nome]

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if cfg.segredo_padrao:
            log.warning("JWT_SECRET ausente: usando o segredo padrão de desenvolvimento")

        yield

        await asyncio.gather(*(c.aclose() for c in clientes.values()))

    app = create_app(
        NOME,
        version=VERSAO,
        include_health=False,
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Health agregado
    # ------------------------------------------------------------------

    async def consultar(
        nome: str,
        url: str,
    ) -> tuple[str, DependenciaSaude]:
        inicio = time.perf_counter()

        sonda = ServiceClient(
            base_url=url,
            timeout=cfg.health_timeout,
            transport=transport,
        )

        try:
            async with sonda:
                resposta = await sonda.get("/health")

            ms = round(
                (time.perf_counter() - inicio) * 1000,
                1,
            )

            if resposta.status_code == 200:
                return nome, DependenciaSaude(
                    status="up",
                    latencyMs=ms,
                )

            return nome, DependenciaSaude(
                status="down",
                erro=f"HTTP {resposta.status_code}",
            )

        except Exception as exc:
            return nome, DependenciaSaude(
                status="down",
                erro=type(exc).__name__,
            )

    @app.get(
        "/health",
        response_model=GatewayHealth,
        tags=["infra"],
    )
    async def health() -> GatewayHealth:
        alvos = [(nome, url) for nome, url in urls.items() if nome != NOME]

        deps = dict(await asyncio.gather(*(consultar(nome, url) for nome, url in alvos)))

        todos_ok = all(dependencia.status == "up" for dependencia in deps.values())

        return GatewayHealth(
            status="ok" if todos_ok else "degraded",
            service=NOME,
            version=VERSAO,
            dependencies=deps,
        )

    # ------------------------------------------------------------------
    # Autenticação JWT
    # ------------------------------------------------------------------

    def autenticar(
        request: Request,
    ) -> tuple[Claims | None, str]:
        """Valida o JWT e retorna suas claims."""
        token = _bearer(request)

        if token is None:
            return None, "ausente"

        try:
            claims = validar_token(
                token,
                segredo=cfg.jwt_secret,
                agora=agora(),
            )

            # Rejeita perfis desconhecidos.
            Perfil(claims.perfil)

        except TokenInvalido as exc:
            motivo = "expirado" if exc.codigo == "expirado" else "invalido"
            return None, motivo

        except ValueError:
            return None, "invalido"

        return claims, ""

    # ------------------------------------------------------------------
    # Proxy HTTP
    # ------------------------------------------------------------------

    async def proxy(
        request: Request,
        prefixo: str,
        caminho: str = "",
    ) -> Response:
        del prefixo, caminho

        path = request.url.path

        try:
            destino = resolver(path)

        except CaminhoInvalido as exc:
            raise AppError(
                400,
                "caminho_invalido",
                "Caminho inválido.",
            ) from exc

        if destino is None or destino.servico not in urls:
            raise AppError(
                404,
                "rota_desconhecida",
                f"Nenhuma rota para {path}.",
            )

        claims, motivo = autenticar(request)

        # Rate limit por usuário autenticado ou endereço IP.
        chave = f"user:{claims.sub}" if claims else f"ip:{_ip(request)}"

        decisao = limitador.permitir(chave)

        if not decisao.permitido:
            raise AppError(
                429,
                "limite_excedido",
                "Muitas requisições. Tente novamente em instantes.",
                headers={
                    "retry-after": str(decisao.retry_after),
                },
            )

        # Rotas privadas exigem JWT válido.
        if claims is None and not rota_publica(
            request.method,
            path,
        ):
            codigo, mensagem = {
                "ausente": (
                    "nao_autenticado",
                    "Token ausente. Envie Authorization: Bearer <jwt>.",
                ),
                "expirado": (
                    "token_expirado",
                    "Token expirado.",
                ),
            }.get(
                motivo,
                (
                    "token_invalido",
                    "Token inválido.",
                ),
            )

            raise AppError(
                401,
                codigo,
                mensagem,
                headers={
                    "www-authenticate": "Bearer",
                },
            )

        corpo = await request.body()

        if len(corpo) > TAMANHO_MAXIMO_CORPO:
            raise AppError(
                413,
                "corpo_grande_demais",
                "Corpo da requisição acima de 1 MiB.",
            )

        alvo = destino.caminho

        if request.url.query:
            alvo += f"?{request.url.query}"

        # Remove cabeçalhos de identidade enviados pelo cliente
        # e prepara os cabeçalhos internos confiáveis.
        headers_internos = dict(
            headers_para_servico(
                request.headers,
                claims,
            )
        )

        # --------------------------------------------------------------
        # Encaminhamento do JWT para rotas protegidas
        # --------------------------------------------------------------

        # Aportes valida novamente o JWT para consultar
        # o histórico do próprio investidor.
        rota_aportes_meus = (
            request.method == "GET"
            and destino.servico == "aportes"
            and destino.caminho == "/aportes/meus"
        )

        # A Identidade valida novamente o JWT para:
        # - consultar o próprio perfil;
        # - bloquear usuários (somente ADMIN);
        # - desbloquear usuários (somente ADMIN).
        rota_identidade_protegida = destino.servico == "identidade" and (
            (request.method == "GET" and destino.caminho == "/identidade/usuarios/me")
            or (
                request.method == "POST"
                and destino.caminho.startswith("/identidade/usuarios/")
                and destino.caminho.endswith(("/bloquear", "/desbloquear"))
            )
        )

        # Encaminha Authorization somente quando necessário.
        # As claims já foram validadas pelo Gateway.
        if claims is not None and (rota_aportes_meus or rota_identidade_protegida):
            token = _bearer(request)

            if token is not None:
                headers_internos["authorization"] = f"Bearer {token}"

        # --------------------------------------------------------------
        # Encaminhamento da requisição ao microsserviço
        # --------------------------------------------------------------

        try:
            resposta = await cliente(destino.servico).request(
                request.method,
                alvo,
                headers=headers_internos,
                content=corpo,
            )

        except ERROS_DE_CONEXAO as exc:
            log.warning(
                "serviço indisponível",
                extra={
                    "servico": destino.servico,
                    "erro": type(exc).__name__,
                },
            )

            raise AppError(
                503,
                "servico_indisponivel",
                (f"O serviço '{destino.servico}' está indisponível no momento."),
                {
                    "servico": destino.servico,
                },
            ) from exc

        except ERROS_DE_TIMEOUT as exc:
            log.warning(
                "serviço lento",
                extra={
                    "servico": destino.servico,
                },
            )

            raise AppError(
                504,
                "servico_timeout",
                (f"O serviço '{destino.servico}' não respondeu a tempo."),
                {
                    "servico": destino.servico,
                },
            ) from exc

        return Response(
            content=resposta.content,
            status_code=resposta.status_code,
            headers=headers_para_cliente(resposta.headers),
        )

    # ------------------------------------------------------------------
    # Frontend estático servido pelo Gateway
    # ------------------------------------------------------------------

    diretorio_estatico = Path(__file__).resolve().parents[2] / "static"

    @app.get("/", response_class=Response, include_in_schema=False)
    async def index() -> Response:
        index_file = diretorio_estatico / "index.html"
        if not index_file.is_file():
            raise AppError(404, "nao_encontrado", "Página inicial não encontrada.")
        return Response(
            content=index_file.read_bytes(),
            media_type="text/html; charset=utf-8",
        )

    @app.get("/static/{arquivo:path}", response_class=Response, include_in_schema=False)
    async def static_files(arquivo: str) -> Response:
        caminho = (diretorio_estatico / arquivo).resolve()
        # Previne path traversal fora da pasta static
        if not str(caminho).startswith(str(diretorio_estatico.resolve())):
            raise AppError(403, "acesso_negado", "Acesso negado.")
        if not caminho.is_file():
            raise AppError(404, "nao_encontrado", f"Arquivo '{arquivo}' não encontrado.")

        ext = caminho.suffix.lower()
        media_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }
        media_type = media_types.get(ext, "application/octet-stream")
        return Response(content=caminho.read_bytes(), media_type=media_type)

    # ------------------------------------------------------------------
    # Registro das rotas do Gateway
    # ------------------------------------------------------------------

    app.add_api_route(
        "/api/{prefixo}",
        proxy,
        methods=METODOS,
        include_in_schema=False,
    )

    app.add_api_route(
        "/api/{prefixo}/{caminho:path}",
        proxy,
        methods=METODOS,
        include_in_schema=False,
    )

    return app
