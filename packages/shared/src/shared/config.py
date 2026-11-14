"""Configuração por variáveis de ambiente e descoberta de serviços (services.json)."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

SERVICES_FILE_NAME = "services.json"


class ConfigError(Exception):
    """Configuração ausente ou inválida."""


@dataclass(frozen=True)
class ServiceInfo:
    url: str
    port: int


@dataclass(frozen=True)
class Settings:
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    http_timeout: float = 5.0
    services_file: Path | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        try:
            timeout = float(env.get("HTTP_TIMEOUT_SECONDS", "5"))
        except ValueError as exc:
            raise ConfigError("HTTP_TIMEOUT_SECONDS deve ser numérico") from exc
        if timeout <= 0:
            raise ConfigError("HTTP_TIMEOUT_SECONDS deve ser maior que zero")
        arquivo = env.get("SERVICES_FILE")
        return cls(
            log_level=env.get("LOG_LEVEL", "INFO").upper(),
            host=env.get("SERVICE_HOST", "127.0.0.1"),
            http_timeout=timeout,
            services_file=Path(arquivo) if arquivo else None,
        )


def find_services_file(settings: Settings | None = None, start: Path | None = None) -> Path:
    """SERVICES_FILE, ou o services.json mais próximo subindo a partir de `start` (cwd)."""
    settings = settings or Settings.from_env()
    if settings.services_file is not None:
        if not settings.services_file.is_file():
            raise ConfigError(f"SERVICES_FILE não encontrado: {settings.services_file}")
        return settings.services_file
    base = (start or Path.cwd()).resolve()
    for pasta in (base, *base.parents):
        candidato = pasta / SERVICES_FILE_NAME
        if candidato.is_file():
            return candidato
    raise ConfigError(f"{SERVICES_FILE_NAME} não encontrado a partir de {base}")


def load_services(path: Path | None = None) -> dict[str, ServiceInfo]:
    arquivo = path or find_services_file()
    try:
        bruto = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"não foi possível ler {arquivo}: {exc}") from exc
    servicos: dict[str, ServiceInfo] = {}
    for nome, info in bruto.items():
        try:
            servicos[nome] = ServiceInfo(url=str(info["url"]).rstrip("/"), port=int(info["port"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"entrada inválida em {arquivo} para '{nome}'") from exc
    return servicos


def service_info(name: str, path: Path | None = None) -> ServiceInfo:
    servicos = load_services(path)
    if name not in servicos:
        raise ConfigError(f"serviço '{name}' não existe em services.json ({sorted(servicos)})")
    return servicos[name]


def service_url(name: str, path: Path | None = None) -> str:
    """URL base do serviço, ex.: service_url('campanhas') -> 'http://127.0.0.1:3002'."""
    return service_info(name, path).url


def service_port(name: str, path: Path | None = None) -> int:
    return service_info(name, path).port
