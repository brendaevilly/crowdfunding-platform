"""Inicialização do microsserviço de Aportes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aportes.repository import inicializar_banco
from shared.http.app import create_app
from shared.http.runner import run


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepara o banco de dados antes de receber requisições."""
    inicializar_banco()
    yield


app = create_app(
    "aportes",
    lifespan=lifespan,
)


def main() -> None:
    """Executa o serviço na porta configurada em services.json."""
    run(app, "aportes")


if __name__ == "__main__":
    main()
