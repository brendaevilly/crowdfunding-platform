"""Tabela de rotas do gateway: prefixo público -> serviço, e quais rotas dispensam JWT.

O gateway remove só o `/api`: `/api/aportes/x` chega ao serviço Aportes como `/aportes/x`,
então cada serviço é dono do seu próprio namespace (`POST /aportes`, `GET /campanhas/:id/status`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

PREFIXO_API: Final = "/api"

# prefixo da URL pública -> nome do serviço em services.json
PREFIXOS: Final[dict[str, str]] = {
    "identidade": "identidade",
    "campanhas": "campanhas",
    "aportes": "aportes",
    "retornos": "custodia_retornos",
    "notificacoes": "notificacao",
}

# (método, caminho público) que NÃO exigem JWT: cadastro e login.
ROTAS_PUBLICAS: Final = frozenset(
    {
        ("POST", "/api/identidade/usuarios"),
        ("POST", "/api/identidade/login"),
    }
)


class CaminhoInvalido(ValueError):
    """Caminho com segmentos `.`/`..` (tentativa de escapar do prefixo)."""


@dataclass(frozen=True)
class Destino:
    servico: str
    caminho: str  # caminho enviado ao serviço (sem o /api)


def _normalizar(caminho: str) -> str:
    return caminho.rstrip("/") or "/"


def resolver(caminho: str) -> Destino | None:
    """Destino de um caminho público `/api/<prefixo>/...`; None se não houver rota."""
    if not (caminho == PREFIXO_API or caminho.startswith(PREFIXO_API + "/")):
        return None
    interno = caminho[len(PREFIXO_API) :]
    if any(seg in (".", "..") for seg in interno.split("/")):
        raise CaminhoInvalido(caminho)
    prefixo = interno.lstrip("/").split("/", 1)[0]
    servico = PREFIXOS.get(prefixo)
    if servico is None:
        return None
    return Destino(servico=servico, caminho=interno if interno.startswith("/") else "/" + interno)


def rota_publica(metodo: str, caminho: str) -> bool:
    return (metodo.upper(), _normalizar(caminho)) in ROTAS_PUBLICAS
