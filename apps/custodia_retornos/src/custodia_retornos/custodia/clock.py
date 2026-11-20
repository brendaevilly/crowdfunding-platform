"""Relógios injetáveis para apuração de campanhas."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Retorna o instante atual com fuso horário."""


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class AdjustableClock:
    def __init__(self, initial: datetime | None = None) -> None:
        self._current = initial or datetime.now(UTC)
        if self._current.tzinfo is None:
            raise ValueError("O relógio exige data com fuso horário")

    def now(self) -> datetime:
        return self._current

    def advance(self, seconds: float) -> datetime:
        if seconds < 0:
            raise ValueError("O avanço não pode ser negativo")
        self._current += timedelta(seconds=seconds)
        return self._current
