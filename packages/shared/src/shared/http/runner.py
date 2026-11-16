"""Runner uvicorn: sobe o serviço na porta definida em services.json."""

from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

from shared.config import Settings, service_port


def resolve_port(name: str, port: int | None = None) -> int:
    """Prioridade: argumento > env PORT > services.json."""
    if port is not None:
        return port
    if os.environ.get("PORT"):
        return int(os.environ["PORT"])
    return service_port(name)


def run(app: FastAPI | str, name: str, *, port: int | None = None) -> None:
    """Sobe o app (ou 'modulo:app') como processo do serviço `name`."""
    settings = Settings.from_env()
    uvicorn.run(
        app,
        host=settings.host,
        port=resolve_port(name, port),
        log_config=None,  # usa o logging JSON do shared
        access_log=False,  # o middleware já registra cada request
    )
