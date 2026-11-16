"""Middleware ASGI: x-correlation-id (gera se ausente, propaga, vai para todo log) + access log."""

from __future__ import annotations

import logging
import re
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from shared.correlation import (
    CORRELATION_HEADER,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from shared.http.errors import error_response

log = logging.getLogger("shared.http")

_HEADER_BYTES = CORRELATION_HEADER.encode("latin-1")
_VALIDO = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")


def _extrair(scope: Scope) -> str | None:
    for nome, valor in scope["headers"]:
        if nome == _HEADER_BYTES:
            texto = valor.decode("latin-1").strip()
            return texto if _VALIDO.match(texto) else None
    return None


class CorrelationIdMiddleware:
    """Pure ASGI (sem BaseHTTPMiddleware) para o contextvar chegar às rotas e aos logs.

    Também captura exceções não tratadas, devolvendo 500 padronizado já com o header.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cid = _extrair(scope) or new_correlation_id()
        token = set_correlation_id(cid)
        inicio = time.perf_counter()
        status = 500
        iniciou = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, iniciou
            if message["type"] == "http.response.start":
                iniciou = True
                status = message["status"]
                headers = [(k, v) for k, v in message["headers"] if k.lower() != _HEADER_BYTES]
                headers.append((_HEADER_BYTES, cid.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            try:
                await self.app(scope, receive, send_wrapper)
            except Exception:
                log.exception("erro não tratado", extra={"path": scope["path"]})
                if iniciou:
                    raise
                resposta = error_response(500, "internal_error", "Erro interno do servidor.")
                await resposta(scope, receive, send_wrapper)
            log.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "durationMs": round((time.perf_counter() - inicio) * 1000, 2),
                },
            )
        finally:
            reset_correlation_id(token)
