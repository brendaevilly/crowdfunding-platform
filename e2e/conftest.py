"""Fixtures compartilhadas dos testes E2E."""

from __future__ import annotations

import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def aguardar_gateway(timeout: float = 30.0) -> None:
    """Aguarda o Gateway ficar disponível."""
    limite = time.monotonic() + timeout
    url = "http://127.0.0.1:3000/health"

    while time.monotonic() < limite:
        try:
            with urllib.request.urlopen(url, timeout=15) as resposta:
                if resposta.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.3)

    raise RuntimeError("Gateway não ficou disponível em 30 segundos.")


@pytest.fixture(scope="function")
def sistema_e2e():
    """Sobe os microsserviços uma vez para toda a sessão E2E."""

    ambiente = {
        "CUSTODIA_DEV_MODE": "true",
        "CUSTODIA_TAXA_PERCENTUAL": "5",
    }

    import os

    ambiente_completo = os.environ.copy()
    ambiente_completo.update(ambiente)

    processo = subprocess.Popen(
        [
            sys.executable,
            str(RAIZ / "scripts" / "dev.py"),
            "up",
        ],
        cwd=RAIZ,
        env=ambiente_completo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        aguardar_gateway()
        yield processo
    finally:
        if processo.poll() is None:
            if sys.platform == "win32":
                processo.terminate()
            else:
                processo.send_signal(signal.SIGINT)

            try:
                processo.wait(timeout=20)
            except subprocess.TimeoutExpired:
                processo.kill()
                processo.wait(timeout=5)
