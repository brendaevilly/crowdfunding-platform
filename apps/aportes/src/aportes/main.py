"""Inicialização do microsserviço de Aportes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aportes.acl_kyc import consumir_identidade_verificada
from aportes.api import criar_router
from aportes.repository import inicializar_banco
from aportes.status_investidor import consumir_usuario_status_alterado
from contracts.topicos import IDENTIDADE_VERIFICADA, USUARIO_STATUS_ALTERADO
from shared.config import service_url
from shared.http.app import create_app
from shared.http.runner import run
from shared.messaging import configure_messaging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepara o banco de dados antes de receber requisições."""
    inicializar_banco()
    yield


app = create_app(
    "aportes",
    lifespan=lifespan,
)

app.include_router(criar_router())

configure_messaging(
    app,
    service="aportes",
    service_url=service_url("aportes"),
    broker_url=service_url("broker"),
    handlers={
        IDENTIDADE_VERIFICADA: consumir_identidade_verificada,
        USUARIO_STATUS_ALTERADO: consumir_usuario_status_alterado,
    },
)


def main() -> None:
    """Executa o serviço na porta configurada em services.json."""
    run(app, "aportes")


if __name__ == "__main__":
    main()
