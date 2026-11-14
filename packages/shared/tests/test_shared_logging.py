from __future__ import annotations

import json
import logging
import sys

import pytest

from shared.correlation import reset_correlation_id, set_correlation_id
from shared.logging import JsonFormatter, configure_logging


def _registro(msg: str = "ola", **extra: object) -> logging.LogRecord:
    r = logging.LogRecord("meu.logger", logging.INFO, __file__, 1, msg, (), None)
    r.__dict__.update(extra)
    return r


def test_json_formatter_campos_basicos() -> None:
    dados = json.loads(JsonFormatter("aportes").format(_registro("ola")))
    assert dados["service"] == "aportes"
    assert dados["level"] == "INFO"
    assert dados["logger"] == "meu.logger"
    assert dados["message"] == "ola"
    assert dados["correlationId"] is None
    assert dados["ts"].endswith("+00:00")


def test_json_formatter_inclui_correlation_id_e_extras() -> None:
    token = set_correlation_id("abc-123")
    try:
        dados = json.loads(JsonFormatter("x").format(_registro(aporteId="a1", valor=10)))
    finally:
        reset_correlation_id(token)
    assert dados["correlationId"] == "abc-123"
    assert dados["aporteId"] == "a1"
    assert dados["valor"] == 10


def test_json_formatter_exception() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        r = logging.LogRecord("l", logging.ERROR, __file__, 1, "falhou", (), sys.exc_info())
    dados = json.loads(JsonFormatter("x").format(r))
    assert "ValueError: boom" in dados["exception"]


def test_configure_logging_escreve_json_e_e_idempotente(
    capsys: pytest.CaptureFixture[str],
) -> None:
    raiz = logging.getLogger()
    antigos, nivel = raiz.handlers[:], raiz.level
    try:
        configure_logging("svc", "INFO")
        configure_logging("svc", "INFO")
        assert len(raiz.handlers) == 1
        logging.getLogger("teste").info("linha")
        linha = capsys.readouterr().out.strip().splitlines()[-1]
        assert json.loads(linha)["message"] == "linha"
    finally:
        raiz.handlers[:] = antigos
        raiz.setLevel(nivel)
