"""Testes unitários do Circuit Breaker."""

import asyncio

import pytest

from shared.resilience import CircuitBreaker, CircuitOpenError, CircuitState


def test_circuito_inicia_fechado() -> None:
    breaker = CircuitBreaker()

    assert breaker.state == CircuitState.CLOSED
    assert breaker.metrics()["state"] == "closed"


def test_circuito_abre_apos_limiar_de_falhas() -> None:
    async def executar() -> None:
        breaker = CircuitBreaker(failure_threshold=2)

        async def falhar() -> None:
            raise RuntimeError("Serviço indisponível")

        for _ in range(2):
            with pytest.raises(RuntimeError, match="Serviço indisponível"):
                await breaker.call(falhar)

        assert breaker.state == CircuitState.OPEN

        with pytest.raises(CircuitOpenError):
            await breaker.call(falhar)

    asyncio.run(executar())


def test_circuito_recupera_apos_timeout() -> None:
    async def executar() -> None:
        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.01,
        )

        async def falhar() -> None:
            raise RuntimeError("Falha simulada")

        async def funcionar() -> str:
            return "sucesso"

        with pytest.raises(RuntimeError):
            await breaker.call(falhar)

        assert breaker.state == CircuitState.OPEN

        await asyncio.sleep(0.02)

        resultado = await breaker.call(funcionar)

        assert resultado == "sucesso"
        assert breaker.metrics()["state"] == "closed"
        assert breaker.metrics()["failure_count"] == 0

    asyncio.run(executar())


def test_circuito_reabre_se_recuperacao_falhar() -> None:
    async def executar() -> None:
        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.01,
        )

        async def falhar() -> None:
            raise RuntimeError("Falha simulada")

        with pytest.raises(RuntimeError):
            await breaker.call(falhar)

        assert breaker.state == CircuitState.OPEN

        await asyncio.sleep(0.02)

        with pytest.raises(RuntimeError):
            await breaker.call(falhar)

        assert breaker.state == CircuitState.OPEN

    asyncio.run(executar())


def test_circuito_rejeita_chamadas_enquanto_aberto() -> None:
    async def executar() -> None:
        breaker = CircuitBreaker(failure_threshold=1)
        chamadas = 0

        async def falhar() -> None:
            nonlocal chamadas
            chamadas += 1
            raise RuntimeError("Falha")

        with pytest.raises(RuntimeError):
            await breaker.call(falhar)

        with pytest.raises(CircuitOpenError):
            await breaker.call(falhar)

        assert chamadas == 1

    asyncio.run(executar())


def test_circuito_entra_em_meio_aberto_durante_recuperacao() -> None:
    async def executar() -> None:
        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.01,
        )
        iniciou = asyncio.Event()
        liberar = asyncio.Event()

        async def falhar() -> None:
            raise RuntimeError("Falha simulada")

        async def recuperar() -> str:
            iniciou.set()
            await liberar.wait()
            return "recuperado"

        with pytest.raises(RuntimeError):
            await breaker.call(falhar)

        assert breaker.metrics()["state"] == "open"

        await asyncio.sleep(0.02)

        tarefa = asyncio.create_task(breaker.call(recuperar))
        try:
            await asyncio.wait_for(iniciou.wait(), timeout=1.0)

            assert breaker.metrics()["state"] == "half_open"

            liberar.set()
            assert await tarefa == "recuperado"
            assert breaker.metrics()["state"] == "closed"
        finally:
            liberar.set()
            await tarefa

    asyncio.run(executar())


def test_meio_aberto_permite_apenas_uma_chamada() -> None:
    async def executar() -> None:
        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.01,
        )
        iniciou = asyncio.Event()
        liberar = asyncio.Event()

        async def falhar() -> None:
            raise RuntimeError("Falha simulada")

        async def recuperar() -> str:
            iniciou.set()
            await liberar.wait()
            return "sucesso"

        async def segunda_chamada() -> str:
            return "segunda"

        with pytest.raises(RuntimeError):
            await breaker.call(falhar)

        await asyncio.sleep(0.02)

        tarefa = asyncio.create_task(breaker.call(recuperar))
        try:
            await asyncio.wait_for(iniciou.wait(), timeout=1.0)

            assert breaker.metrics()["state"] == "half_open"

            with pytest.raises(CircuitOpenError):
                await breaker.call(segunda_chamada)

            liberar.set()
            assert await tarefa == "sucesso"
            assert breaker.metrics()["state"] == "closed"
        finally:
            liberar.set()
            await tarefa

    asyncio.run(executar())
