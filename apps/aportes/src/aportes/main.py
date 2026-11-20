"""Inicialização do microsserviço de Aportes."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from aportes.acl_kyc import consumir_identidade_verificada
from aportes.api import criar_router
from aportes.cliente_campanhas import ClienteCampanhas
from aportes.reconciliacao_worker import executar_reconciliacao_periodica
from aportes.repository import inicializar_banco
from aportes.status_investidor import consumir_usuario_status_alterado
from contracts.topicos import IDENTIDADE_VERIFICADA, USUARIO_STATUS_ALTERADO
from shared.config import service_url
from shared.http.app import create_app
from shared.http.runner import run
from shared.messaging import configure_messaging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepara o banco e executa a reconciliação periódica."""
    inicializar_banco()

    tarefa = asyncio.create_task(
        executar_reconciliacao_periodica(),
        name="reconciliacao-aportes",
    )

    try:
        yield
    finally:
        tarefa.cancel()
        with suppress(asyncio.CancelledError):
            await tarefa


cliente_campanhas = ClienteCampanhas()

app = create_app(
    "aportes",
    lifespan=lifespan,
    circuit_breakers={"campanhas": cliente_campanhas.circuit_breaker},
)

app.include_router(criar_router(cliente_campanhas=cliente_campanhas))
app.include_router(criar_router(cliente_campanhas=cliente_campanhas), prefix="/aportes")

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
