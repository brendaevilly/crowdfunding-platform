from __future__ import annotations

import base64
import json

import pytest

from shared.auth import (
    EXPIRACAO_PADRAO_SEGUNDOS,
    SEGREDO_DEV,
    TokenInvalido,
    emitir_token,
    expiracao_do_ambiente,
    segredo_do_ambiente,
    validar_token,
)

SEGREDO = "segredo-de-teste"
AGORA = 1_800_000_000.0


def _b64(obj: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def _codigo(token: str, **kw: object) -> str:
    with pytest.raises(TokenInvalido) as exc:
        validar_token(token, segredo=SEGREDO, agora=AGORA, **kw)
    return exc.value.codigo


def test_round_trip() -> None:
    token = emitir_token("u1", "INVESTIDOR", segredo=SEGREDO, agora=AGORA)
    claims = validar_token(token, segredo=SEGREDO, agora=AGORA + 10)
    assert (claims.sub, claims.perfil, claims.iat) == ("u1", "INVESTIDOR", int(AGORA))
    assert claims.exp == int(AGORA) + EXPIRACAO_PADRAO_SEGUNDOS


def test_expirado() -> None:
    token = emitir_token("u1", "INVESTIDOR", segredo=SEGREDO, expira_em_segundos=60, agora=AGORA)
    assert validar_token(token, segredo=SEGREDO, agora=AGORA + 59).sub == "u1"
    with pytest.raises(TokenInvalido) as exc:
        validar_token(token, segredo=SEGREDO, agora=AGORA + 60)
    assert exc.value.codigo == "expirado"


def test_segredo_errado_e_adulteracao() -> None:
    token = emitir_token("u1", "INVESTIDOR", segredo=SEGREDO, agora=AGORA)
    with pytest.raises(TokenInvalido) as exc:
        validar_token(token, segredo="outro", agora=AGORA)
    assert exc.value.codigo == "assinatura"
    cab, _, assin = token.split(".")
    forjado = f"{cab}.{_b64({'sub': 'admin', 'perfil': 'X', 'exp': AGORA + 99})}.{assin}"
    assert _codigo(forjado) == "assinatura"


def test_algoritmo_none_e_recusado() -> None:
    cabecalho = _b64({"alg": "none", "typ": "JWT"})
    corpo = f"{cabecalho}.{_b64({'sub': 'u', 'perfil': 'P', 'exp': AGORA + 9})}"
    assert _codigo(corpo + ".") == "assinatura"
    assert _codigo(corpo + ".xyz") == "assinatura"


@pytest.mark.parametrize("token", ["", "abc", "a.b", "a.b.c.d", "!!!.???.***", "x" * 5000])
def test_malformado(token: str) -> None:
    assert _codigo(token) == "malformado"


@pytest.mark.parametrize(
    "claims",
    [
        {"perfil": "P", "exp": AGORA + 9},
        {"sub": "", "perfil": "P", "exp": AGORA + 9},
        {"sub": "u", "exp": AGORA + 9},
        {"sub": "u", "perfil": "P"},
        {"sub": "u", "perfil": "P", "exp": True},
        {"sub": "u", "perfil": "P", "exp": "amanha"},
    ],
)
def test_claims_obrigatorios(claims: dict[str, object]) -> None:
    from shared.auth import _assinar  # noqa: PLC2701

    corpo = f"{_b64({'alg': 'HS256', 'typ': 'JWT'})}.{_b64(claims)}"
    assert _codigo(f"{corpo}.{_assinar(corpo, SEGREDO)}") == "claims"


def test_nbf_no_futuro() -> None:
    from shared.auth import _assinar  # noqa: PLC2701

    claims = {"sub": "u", "perfil": "P", "exp": AGORA + 99, "nbf": AGORA + 50}
    corpo = f"{_b64({'alg': 'HS256'})}.{_b64(claims)}"
    assert _codigo(f"{corpo}.{_assinar(corpo, SEGREDO)}") == "claims"


def test_segredo_do_ambiente() -> None:
    assert segredo_do_ambiente({"JWT_SECRET": " abc "}) == ("abc", False)
    assert segredo_do_ambiente({}) == (SEGREDO_DEV, True)
    assert segredo_do_ambiente({"JWT_SECRET": "  "}) == (SEGREDO_DEV, True)


def test_expiracao_do_ambiente() -> None:
    assert expiracao_do_ambiente({"JWT_EXPIRES_MINUTES": "2"}) == 120
    assert expiracao_do_ambiente({}) == EXPIRACAO_PADRAO_SEGUNDOS
    assert expiracao_do_ambiente({"JWT_EXPIRES_MINUTES": "-1"}) == EXPIRACAO_PADRAO_SEGUNDOS
    assert expiracao_do_ambiente({"JWT_EXPIRES_MINUTES": "x"}) == EXPIRACAO_PADRAO_SEGUNDOS
