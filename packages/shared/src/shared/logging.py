"""Logging JSON estruturado, uma linha por evento, sempre com o correlation-id atual."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from shared.correlation import get_correlation_id

_PADRAO = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        dados: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
            "correlationId": get_correlation_id(),
        }
        for chave, valor in record.__dict__.items():
            if chave not in _PADRAO and chave not in dados:
                dados[chave] = valor
        if record.exc_info:
            dados["exception"] = self.formatException(record.exc_info)
        return json.dumps(dados, ensure_ascii=False, default=str)


def configure_logging(service: str, level: str = "INFO") -> None:
    """Configura o root logger com saída JSON no stdout (idempotente)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    raiz = logging.getLogger()
    raiz.handlers[:] = [handler]
    raiz.setLevel(level.upper())
