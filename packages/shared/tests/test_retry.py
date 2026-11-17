"""Testes de retry, backoff e timeout."""

import asyncio

import pytest

from shared.resilience import RetryConfig, retry_with_backoff


def test_retry_sucesso_na_primeira_tentativa() -> None:
    async def executar() -> None:
        chamadas = 0

        async def operacao() -> str:
            nonlocal chamadas
            chamadas += 1
            return "sucesso"

        resultado = await retry_with_backoff(
            operacao,
            RetryConfig(max_attempts=3, initial_backoff=0),
        )

        assert resultado == "sucesso"
        assert chamadas == 1

    asyncio.run(executar())


def test_retry_recupera_apos_falhas() -> None:
    async def executar() -> None:
        chamadas = 0

        async def operacao() -> str:
            nonlocal chamadas
            chamadas += 1
            if chamadas < 3:
                raise ConnectionError("Serviço indisponível")
            return "recuperado"

        resultado = await retry_with_backoff(
            operacao,
            RetryConfig(max_attempts=3, initial_backoff=0),
        )

        assert resultado == "recuperado"
        assert chamadas == 3

    asyncio.run(executar())


def test_retry_esgota_tentativas() -> None:
    async def executar() -> None:
        chamadas = 0

        async def operacao() -> None:
            nonlocal chamadas
            chamadas += 1
            raise ConnectionError("Falha persistente")

        with pytest.raises(ConnectionError, match="Falha persistente"):
            await retry_with_backoff(
                operacao,
                RetryConfig(max_attempts=3, initial_backoff=0),
            )

        assert chamadas == 3

    asyncio.run(executar())


def test_retry_nao_repete_erro_nao_configurado() -> None:
    async def executar() -> None:
        chamadas = 0

        async def operacao() -> None:
            nonlocal chamadas
            chamadas += 1
            raise ValueError("Erro de validação")

        with pytest.raises(ValueError, match="Erro de validação"):
            await retry_with_backoff(
                operacao,
                RetryConfig(max_attempts=3, initial_backoff=0),
            )

        assert chamadas == 1

    asyncio.run(executar())


def test_retry_timeout() -> None:
    async def executar() -> None:
        chamadas = 0

        async def operacao() -> None:
            nonlocal chamadas
            chamadas += 1
            await asyncio.sleep(0.1)

        with pytest.raises(TimeoutError):
            await retry_with_backoff(
                operacao,
                RetryConfig(
                    max_attempts=2,
                    initial_backoff=0,
                    timeout=0.01,
                ),
            )

        assert chamadas == 2

    asyncio.run(executar())


def test_retry_configuracao_invalida() -> None:
    with pytest.raises(ValueError):
        RetryConfig(max_attempts=0)

    with pytest.raises(ValueError):
        RetryConfig(initial_backoff=-1)

    with pytest.raises(ValueError):
        RetryConfig(timeout=0)
