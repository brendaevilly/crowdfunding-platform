"""Testes do worker periódico de reconciliação."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from aportes.reconciliacao import ResultadoReconciliacao
from aportes.reconciliacao_worker import (
    executar_reconciliacao_periodica,
    obter_intervalo_reconciliacao,
)


def test_intervalo_padrao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "APORTES_RECONCILIACAO_INTERVALO_SEGUNDOS",
        raising=False,
    )

    assert obter_intervalo_reconciliacao() == 60


def test_intervalo_configurado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "APORTES_RECONCILIACAO_INTERVALO_SEGUNDOS",
        "30",
    )

    assert obter_intervalo_reconciliacao() == 30


@pytest.mark.parametrize("valor", ["0", "-1", "abc"])
def test_intervalo_invalido(
    monkeypatch: pytest.MonkeyPatch,
    valor: str,
) -> None:
    monkeypatch.setenv(
        "APORTES_RECONCILIACAO_INTERVALO_SEGUNDOS",
        valor,
    )

    with pytest.raises(ValueError):
        obter_intervalo_reconciliacao()


def test_worker_executa_reconciliacao(
    tmp_path: Path,
) -> None:
    async def executar() -> None:
        executou = asyncio.Event()

        def reconciliacao_simulada(
            *,
            data_dir: str | Path,
        ) -> ResultadoReconciliacao:
            assert data_dir == tmp_path
            executou.set()
            return ResultadoReconciliacao(
                pendencias_sinalizadas=2,
                prazo_minutos=15,
            )

        with patch(
            "aportes.reconciliacao_worker.reconciliar_aportes",
            side_effect=reconciliacao_simulada,
        ):
            tarefa = asyncio.create_task(
                executar_reconciliacao_periodica(
                    data_dir=tmp_path,
                    intervalo_segundos=60,
                )
            )

            try:
                await asyncio.wait_for(executou.wait(), timeout=2)
            finally:
                tarefa.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await tarefa

    asyncio.run(executar())


def test_worker_rejeita_intervalo_invalido(
    tmp_path: Path,
) -> None:
    async def executar() -> None:
        with pytest.raises(ValueError):
            await executar_reconciliacao_periodica(
                data_dir=tmp_path,
                intervalo_segundos=0,
            )

    asyncio.run(executar())
