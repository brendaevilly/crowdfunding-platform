"""Testes do limite de concorrência (Bulkhead)."""

import asyncio

import pytest

from shared.resilience import Bulkhead


def test_bulkhead_limita_concorrencia() -> None:
    async def executar() -> None:
        bulkhead = Bulkhead(max_concurrent=2)
        ativos = 0
        maximo_observado = 0

        async def operacao() -> None:
            nonlocal ativos, maximo_observado

            ativos += 1
            maximo_observado = max(maximo_observado, ativos)
            await asyncio.sleep(0.01)
            ativos -= 1

        await asyncio.gather(*(bulkhead.call(operacao) for _ in range(10)))

        assert maximo_observado == 2
        assert bulkhead.metrics()["active"] == 0

    asyncio.run(executar())


def test_bulkhead_libera_vaga_apos_erro() -> None:
    async def executar() -> None:
        bulkhead = Bulkhead(max_concurrent=1)

        async def falhar() -> None:
            raise RuntimeError("Falha simulada")

        async def funcionar() -> str:
            return "sucesso"

        with pytest.raises(RuntimeError):
            await bulkhead.call(falhar)

        assert bulkhead.metrics()["active"] == 0
        assert await bulkhead.call(funcionar) == "sucesso"

    asyncio.run(executar())


def test_bulkhead_configuracao_invalida() -> None:
    with pytest.raises(ValueError):
        Bulkhead(max_concurrent=0)
