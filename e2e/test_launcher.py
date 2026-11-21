"""Critérios de aceite da issue #9: sobe tudo em < 15s e Ctrl+C não deixa portas ocupadas."""

from __future__ import annotations

import json
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform == "win32", reason="SIGINT simulado só em POSIX"),
]

RAIZ = Path(__file__).resolve().parents[1]
SERVICOS: dict[str, dict[str, object]] = json.loads(
    (RAIZ / "services.json").read_text(encoding="utf-8")
)
PORTAS = [int(str(info["port"])) for info in SERVICOS.values()]


def _porta_aberta(porta: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", porta)) == 0


def _health(url: str) -> int:
    with urllib.request.urlopen(f"{url}/health", timeout=2) as r:
        return int(r.status)


def _subir(*args: str) -> tuple[subprocess.Popen[str], float, list[str]]:
    proc = subprocess.Popen(
        [sys.executable, str(RAIZ / "scripts" / "dev.py"), *args],
        cwd=RAIZ,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    inicio = time.monotonic()
    linhas: list[str] = []
    assert proc.stdout is not None
    for linha in proc.stdout:
        linhas.append(linha)
        if "Tudo no ar" in linha:
            return proc, time.monotonic() - inicio, linhas
        if time.monotonic() - inicio > 30:
            break
    proc.kill()
    pytest.fail("launcher não subiu:\n" + "".join(linhas[-20:]))


def _encerrar(proc: subprocess.Popen[str]) -> None:
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("launcher não encerrou com SIGINT")


def test_make_dev_sobe_tudo_em_menos_de_15s_e_ctrl_c_libera_as_portas() -> None:
    assert not any(_porta_aberta(p) for p in PORTAS), "portas já ocupadas antes do teste"
    proc, segundos, _ = _subir("up")
    try:
        assert segundos < 15
        for nome, info in SERVICOS.items():
            assert _health(str(info["url"])) == 200, nome
    finally:
        _encerrar(proc)
    assert proc.returncode == 0
    assert not any(_porta_aberta(p) for p in PORTAS), "Ctrl+C deixou portas ocupadas"


def test_kill_e_start_de_um_servico() -> None:
    proc, _, _ = _subir("only", "broker", "aportes", "campanhas")
    try:
        comando = [sys.executable, str(RAIZ / "scripts" / "dev.py")]
        out = subprocess.run([*comando, "kill", "aportes"], capture_output=True, text=True)
        assert out.returncode == 0, out.stdout + out.stderr
        assert not _porta_aberta(3003)
        assert _health("http://127.0.0.1:3002") == 200  # o outro serviço segue no ar

        out = subprocess.run([*comando, "start", "aportes"], capture_output=True, text=True)
        assert out.returncode == 0, out.stdout + out.stderr
        assert _health("http://127.0.0.1:3003") == 200
    finally:
        _encerrar(proc)
    assert not _porta_aberta(3003)
    assert not _porta_aberta(3002)
