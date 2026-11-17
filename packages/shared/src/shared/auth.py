"""JWT HS256 com a biblioteca padrão. A Identidade emite; o Gateway valida (segredo em env).

Só aceita `alg=HS256` (nunca `none`), compara a assinatura em tempo constante e exige `exp`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass

SEGREDO_DEV = "troque-este-segredo-em-dev"
EXPIRACAO_PADRAO_SEGUNDOS = 3600
_TAMANHO_MAXIMO = 4096
_CABECALHO = {"alg": "HS256", "typ": "JWT"}


class TokenInvalido(Exception):
    """Token recusado. `codigo`: malformado | assinatura | expirado | claims."""

    def __init__(self, codigo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.codigo = codigo


@dataclass(frozen=True)
class Claims:
    sub: str  # id do usuário
    perfil: str
    iat: int
    exp: int


def segredo_do_ambiente(env: Mapping[str, str] | None = None) -> tuple[str, bool]:
    """(segredo, é_o_padrão_de_dev). Em dev sem JWT_SECRET usa o segredo padrão."""
    env = os.environ if env is None else env
    valor = env.get("JWT_SECRET", "").strip()
    return (valor, False) if valor else (SEGREDO_DEV, True)


def expiracao_do_ambiente(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    try:
        minutos = float(env.get("JWT_EXPIRES_MINUTES", ""))
    except ValueError:
        return EXPIRACAO_PADRAO_SEGUNDOS
    return int(minutos * 60) if minutos > 0 else EXPIRACAO_PADRAO_SEGUNDOS


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode("ascii")


def _b64_decodificar(texto: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))
    except (binascii.Error, ValueError) as exc:
        raise TokenInvalido("malformado", "base64 inválido") from exc


def _assinar(corpo: str, segredo: str) -> str:
    return _b64(hmac.new(segredo.encode("utf-8"), corpo.encode("ascii"), hashlib.sha256).digest())


def emitir_token(
    sub: str,
    perfil: str,
    *,
    segredo: str,
    expira_em_segundos: int = EXPIRACAO_PADRAO_SEGUNDOS,
    agora: float | None = None,
) -> str:
    emitido = int(time.time() if agora is None else agora)
    claims = {"sub": sub, "perfil": perfil, "iat": emitido, "exp": emitido + expira_em_segundos}
    corpo = ".".join(
        _b64(json.dumps(parte, separators=(",", ":")).encode("utf-8"))
        for parte in (_CABECALHO, claims)
    )
    return f"{corpo}.{_assinar(corpo, segredo)}"


def _objeto_json(texto: str) -> dict[str, object]:
    try:
        valor = json.loads(_b64_decodificar(texto))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TokenInvalido("malformado", "JSON inválido") from exc
    if not isinstance(valor, dict):
        raise TokenInvalido("malformado", "esperado objeto JSON")
    return valor


def validar_token(token: str, *, segredo: str, agora: float | None = None) -> Claims:
    if not token or len(token) > _TAMANHO_MAXIMO:
        raise TokenInvalido("malformado", "token vazio ou grande demais")
    partes = token.split(".")
    if len(partes) != 3:
        raise TokenInvalido("malformado", "esperado header.payload.assinatura")
    cabecalho = _objeto_json(partes[0])
    if cabecalho.get("alg") != "HS256":
        raise TokenInvalido("assinatura", "algoritmo não suportado")
    esperada = _assinar(f"{partes[0]}.{partes[1]}", segredo)
    if not hmac.compare_digest(esperada.encode("ascii"), partes[2].encode("utf-8", "replace")):
        raise TokenInvalido("assinatura", "assinatura inválida")

    dados = _objeto_json(partes[1])
    sub, perfil, exp, iat = (dados.get(k) for k in ("sub", "perfil", "exp", "iat"))
    if not isinstance(sub, str) or not sub or not isinstance(perfil, str) or not perfil:
        raise TokenInvalido("claims", "sub e perfil são obrigatórios")
    if isinstance(exp, bool) or not isinstance(exp, int | float):
        raise TokenInvalido("claims", "exp é obrigatório")
    agora_s = time.time() if agora is None else agora
    if exp <= agora_s:
        raise TokenInvalido("expirado", "token expirado")
    nbf = dados.get("nbf")
    if isinstance(nbf, int | float) and not isinstance(nbf, bool) and nbf > agora_s:
        raise TokenInvalido("claims", "token ainda não é válido")
    emitido = int(iat) if isinstance(iat, int | float) and not isinstance(iat, bool) else 0
    return Claims(sub=sub, perfil=perfil, iat=emitido, exp=int(exp))
