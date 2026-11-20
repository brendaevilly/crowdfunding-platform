"""Testes do scheduler periódico da custódia."""

import asyncio
from pathlib import Path

import pytest

import custodia_retornos.custodia.scheduler as modulo_scheduler
from custodia_retornos.custodia.clock import AdjustableClock


def test_scheduler_executa_apuracao_periodicamente(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    chamadas: list[int] = []

    def apurar(clock: AdjustableClock, data_dir: Path) -> int:
        chamadas.append(1)
        return 0

    monkeypatch.setattr(
        modulo_scheduler,
        "apurar_pendentes",
        apurar,
    )

    async def executar() -> None:
        tarefa = asyncio.create_task(
            modulo_scheduler.executar_scheduler(
                AdjustableClock(),
                tmp_path,
                intervalo=0.01,
            )
        )

        await asyncio.sleep(0.06)

        tarefa.cancel()

        with pytest.raises(asyncio.CancelledError):
            await tarefa

    asyncio.run(executar())

    assert len(chamadas) >= 2


def test_scheduler_rejeita_intervalo_invalido(
    tmp_path: Path,
) -> None:
    async def executar() -> None:
        with pytest.raises(ValueError, match="Intervalo deve ser positivo"):
            await modulo_scheduler.executar_scheduler(
                AdjustableClock(),
                tmp_path,
                intervalo=0,
            )

    asyncio.run(executar())
