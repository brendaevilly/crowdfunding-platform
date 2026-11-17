"""Montagem da requisição/resposta do proxy: headers seguros e identidade injetada."""

from __future__ import annotations

from collections.abc import Mapping

from shared.auth import Claims

# hop-by-hop (RFC 9110) e headers que o gateway controla.
_NAO_REPASSAR_REQUISICAO = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
        "authorization",  # o serviço confia em x-user-*, não no token
        "x-user-id",  # anti-spoof: nunca aceitar do cliente
        "x-user-perfil",
    }
)
_NAO_REPASSAR_RESPOSTA = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",  # httpx já decodifica o corpo; o tamanho é recalculado
        "content-encoding",
        "x-correlation-id",  # o middleware do gateway define o seu
    }
)


def headers_para_servico(originais: Mapping[str, str], usuario: Claims | None) -> dict[str, str]:
    headers = {k: v for k, v in originais.items() if k.lower() not in _NAO_REPASSAR_REQUISICAO}
    if usuario is not None:
        headers["x-user-id"] = usuario.sub
        headers["x-user-perfil"] = usuario.perfil
    return headers


def headers_para_cliente(originais: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in originais.items() if k.lower() not in _NAO_REPASSAR_RESPOSTA}
