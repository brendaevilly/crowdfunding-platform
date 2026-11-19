"""Testes da consulta de campanhas com circuit breaker."""

import asyncio

import httpx
import pytest

from aportes.cliente_campanhas import (
    CampanhaIndisponivelError,
    ClienteCampanhas,
)
from shared.http.client import ServiceClient
from shared.resilience import CircuitBreaker, CircuitState


@pytest.fixture
def anyio_backend() -> str:
    """Executa os testes assíncronos usando asyncio."""
    return "asyncio"


def criar_cliente(
    status_code: int = 200,
    status: str = "PUBLICADA",
    *,
    indisponivel: bool = False,
    circuit_breaker: CircuitBreaker | None = None,
) -> ClienteCampanhas:
    """Cria um cliente HTTP simulado, sem depender de Campanhas."""

    def responder(request: httpx.Request) -> httpx.Response:
        if indisponivel:
            raise httpx.ConnectError(
                "Campanhas indisponível",
                request=request,
            )

        return httpx.Response(
            status_code,
            json={
                "campanhaId": "campanha-1",
                "status": status,
            },
        )

    transport = httpx.MockTransport(responder)

    service_client = ServiceClient(
        base_url="http://campanhas.test",
        timeout=0.5,
        transport=transport,
    )

    return ClienteCampanhas(
        timeout=0.5,
        client=service_client,
        circuit_breaker=circuit_breaker,
    )


@pytest.mark.anyio
async def test_campanha_publicada_aceita_aportes() -> None:
    """Campanhas publicadas permitem novos aportes."""
    cliente = criar_cliente(status="PUBLICADA")

    try:
        assert await cliente.aceita_aportes("campanha-1")
    finally:
        await cliente.aclose()


@pytest.mark.anyio
async def test_campanha_encerrada_rejeita_aportes() -> None:
    """Campanhas encerradas não permitem novos aportes."""
    cliente = criar_cliente(status="ENCERRADA")

    try:
        assert not await cliente.aceita_aportes("campanha-1")
    finally:
        await cliente.aclose()


@pytest.mark.anyio
async def test_campanhas_indisponivel_rejeita_consulta() -> None:
    """Falhas de conexão impedem a confirmação do status."""
    cliente = criar_cliente(indisponivel=True)

    try:
        with pytest.raises(CampanhaIndisponivelError):
            await cliente.aceita_aportes("campanha-1")
    finally:
        await cliente.aclose()


@pytest.mark.anyio
async def test_circuit_breaker_abre_apos_falhas() -> None:
    """O circuito abre após atingir o limite de falhas."""
    circuito = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout=30.0,
    )

    cliente = criar_cliente(
        indisponivel=True,
        circuit_breaker=circuito,
    )

    try:
        for _ in range(2):
            with pytest.raises(CampanhaIndisponivelError):
                await cliente.aceita_aportes("campanha-1")

        assert circuito.state == CircuitState.OPEN

        with pytest.raises(CampanhaIndisponivelError):
            await cliente.aceita_aportes("campanha-1")
    finally:
        await cliente.aclose()


@pytest.mark.anyio
async def test_circuit_breaker_recupera_apos_falha() -> None:
    """O circuito volta a fechar após uma consulta bem-sucedida."""
    circuito = CircuitBreaker(
        failure_threshold=1,
        recovery_timeout=0.01,
    )

    cliente_falha = criar_cliente(
        indisponivel=True,
        circuit_breaker=circuito,
    )

    try:
        with pytest.raises(CampanhaIndisponivelError):
            await cliente_falha.aceita_aportes("campanha-1")

        assert circuito.metrics()["state"] == CircuitState.OPEN.value
    finally:
        await cliente_falha.aclose()

    cliente_recuperado = criar_cliente(
        status="PUBLICADA",
        circuit_breaker=circuito,
    )

    try:
        await asyncio.sleep(0.02)

        assert await cliente_recuperado.aceita_aportes("campanha-1")
        assert circuito.metrics()["state"] == CircuitState.CLOSED.value
    finally:
        await cliente_recuperado.aclose()
