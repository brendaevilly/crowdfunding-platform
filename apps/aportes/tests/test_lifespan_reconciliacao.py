"""Testes do ciclo de vida do worker de reconciliação."""

import asyncio
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI

from aportes.main import lifespan


def test_lifespan_inicia_e_cancela_worker(tmp_path: Path) -> None:
    """Verifica inicialização e encerramento do worker."""

    async def executar() -> None:
        iniciou = asyncio.Event()
        encerrou = asyncio.Event()

        async def worker_simulado() -> None:
            iniciou.set()
            try:
                await asyncio.Event().wait()
            finally:
                encerrou.set()

        with (
            patch(
                "aportes.main.inicializar_banco",
            ) as inicializar,
            patch(
                "aportes.main.executar_reconciliacao_periodica",
                side_effect=worker_simulado,
            ),
        ):
            async with lifespan(FastAPI()):
                inicializar.assert_called_once_with()
                await asyncio.wait_for(iniciou.wait(), timeout=2)

            assert encerrou.is_set()

    asyncio.run(executar())
