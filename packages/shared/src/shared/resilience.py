"""Padrões de resiliência compartilhados entre os microsserviços."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TypeVar

T = TypeVar("T")


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Chamada rejeitada porque o circuito está aberto."""


class CircuitBreaker:
    """Circuit breaker com limiar de falhas e janela configuráveis."""

    def __init__(
        self,
        failure_threshold: int = 3,
        failure_window: float = 60.0,
        recovery_timeout: float = 30.0,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold deve ser positivo")
        if failure_window <= 0 or recovery_timeout <= 0:
            raise ValueError("Os intervalos devem ser positivos")

        self.failure_threshold = failure_threshold
        self.failure_window = failure_window
        self.recovery_timeout = recovery_timeout

        self.state = CircuitState.CLOSED
        self._failures: deque[float] = deque()
        self._opened_at: float | None = None
        self._probe_in_progress = False
        self._lock = asyncio.Lock()

    def _remove_expired_failures(self, now: float) -> None:
        while self._failures and now - self._failures[0] > self.failure_window:
            self._failures.popleft()

    async def call(self, operation: Callable[[], Awaitable[T]]) -> T:
        """Executa a operação respeitando o estado do circuito."""
        async with self._lock:
            now = time.monotonic()

            if self.state == CircuitState.OPEN:
                if self._opened_at is not None and now - self._opened_at >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                else:
                    raise CircuitOpenError("Circuito aberto")

            if self.state == CircuitState.HALF_OPEN:
                if self._probe_in_progress:
                    raise CircuitOpenError("Teste de recuperação em andamento")
                self._probe_in_progress = True

        try:
            result = await operation()
        except Exception:
            async with self._lock:
                now = time.monotonic()

                if self.state == CircuitState.HALF_OPEN:
                    self._open(now)
                    self._probe_in_progress = False
                elif self.state == CircuitState.CLOSED:
                    self._remove_expired_failures(now)
                    self._failures.append(now)

                    if len(self._failures) >= self.failure_threshold:
                        self._open(now)
            raise

        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                self._failures.clear()
                self._opened_at = None
                self._probe_in_progress = False

        return result

    def _open(self, now: float) -> None:
        self.state = CircuitState.OPEN
        self._opened_at = now

    def metrics(self) -> dict[str, str | int]:
        """Retorna métricas básicas para integração com /health."""
        return {
            "state": self.state.value,
            "failure_count": len(self._failures),
            "failure_threshold": self.failure_threshold,
        }


class RetryConfig:
    """Configuração das tentativas e do tempo de espera."""

    def __init__(
        self,
        max_attempts: int = 3,
        initial_backoff: float = 0.1,
        timeout: float = 5.0,
        retry_exceptions: tuple[type[Exception], ...] = (
            TimeoutError,
            ConnectionError,
        ),
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts deve ser positivo")
        if initial_backoff < 0:
            raise ValueError("initial_backoff não pode ser negativo")
        if timeout <= 0:
            raise ValueError("timeout deve ser positivo")
        if not retry_exceptions:
            raise ValueError("retry_exceptions não pode ser vazio")

        self.max_attempts = max_attempts
        self.initial_backoff = initial_backoff
        self.timeout = timeout
        self.retry_exceptions = retry_exceptions


async def retry_with_backoff[T](
    operation: Callable[[], Awaitable[T]],
    config: RetryConfig | None = None,
) -> T:
    """Executa operação com timeout por tentativa e backoff exponencial.

    Repete apenas exceções configuradas. Após esgotar as tentativas,
    propaga a última exceção.
    """
    settings = config if config is not None else RetryConfig()

    for attempt in range(settings.max_attempts):
        try:
            return await asyncio.wait_for(
                operation(),
                timeout=settings.timeout,
            )
        except settings.retry_exceptions:
            if attempt == settings.max_attempts - 1:
                raise

            delay = settings.initial_backoff * (2**attempt)
            await asyncio.sleep(delay)

    raise RuntimeError("Nenhuma tentativa foi executada")


class Bulkhead:
    """Limita a quantidade de operações assíncronas simultâneas."""

    def __init__(self, max_concurrent: int = 5) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent deve ser positivo")

        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active = 0

    async def call[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        """Executa uma operação respeitando o limite de concorrência."""
        async with self._semaphore:
            self._active += 1
            try:
                return await operation()
            finally:
                self._active -= 1

    def metrics(self) -> dict[str, int]:
        """Retorna métricas simples de concorrência."""
        return {
            "active": self._active,
            "max_concurrent": self.max_concurrent,
        }
