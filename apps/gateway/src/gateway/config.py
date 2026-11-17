"""Configuração do gateway por variáveis de ambiente."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from shared.auth import segredo_do_ambiente
from shared.config import ConfigError, Settings


@dataclass(frozen=True)
class GatewaySettings:
    jwt_secret: str
    segredo_padrao: bool = False  # True: JWT_SECRET ausente, usando o segredo de dev
    rate_limit_requests: int = 100
    rate_limit_window: float = 60.0
    upstream_timeout: float = 5.0
    health_timeout: float = 1.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> GatewaySettings:
        env = os.environ if env is None else env
        segredo, padrao = segredo_do_ambiente(env)
        try:
            limite = int(env.get("RATE_LIMIT_REQUESTS", "100"))
            janela = float(env.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
        except ValueError as exc:
            raise ConfigError("RATE_LIMIT_* devem ser numéricos") from exc
        if limite <= 0 or janela <= 0:
            raise ConfigError("RATE_LIMIT_REQUESTS e RATE_LIMIT_WINDOW_SECONDS devem ser > 0")
        return cls(
            jwt_secret=segredo,
            segredo_padrao=padrao,
            rate_limit_requests=limite,
            rate_limit_window=janela,
            upstream_timeout=Settings.from_env(env).http_timeout,
        )
