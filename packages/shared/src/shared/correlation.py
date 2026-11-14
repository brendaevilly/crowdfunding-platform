"""Correlation ID: gerado no gateway e propagado em header HTTP, eventos e logs."""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

CORRELATION_HEADER = "x-correlation-id"

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def get_correlation_id() -> str | None:
    """Correlation ID da requisição/tarefa atual (None fora de um contexto)."""
    return _correlation_id.get()


def set_correlation_id(value: str) -> Token[str | None]:
    return _correlation_id.set(value)


def reset_correlation_id(token: Token[str | None]) -> None:
    _correlation_id.reset(token)
