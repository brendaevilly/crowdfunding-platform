"""Configuração das tentativas de entrega do broker."""

import os
from datetime import UTC, datetime, timedelta


def max_attempts() -> int:
    """Quantidade máxima de tentativas de entrega."""
    return max(
        1,
        int(os.getenv("BROKER_MAX_ATTEMPTS", "5")),
    )


def retry_delay(attempt: int) -> int:
    """Calcula o intervalo de retry com backoff exponencial."""
    base = max(
        1,
        int(os.getenv("BROKER_RETRY_BASE_SECONDS", "2")),
    )
    maximum = max(
        base,
        int(os.getenv("BROKER_RETRY_MAX_SECONDS", "60")),
    )

    return min(
        base * (1 << max(0, attempt - 1)),
        maximum,
    )


def next_attempt_at(attempt: int) -> str:
    """Data UTC da próxima tentativa."""
    next_time = datetime.now(UTC) + timedelta(seconds=retry_delay(attempt))

    return next_time.strftime("%Y-%m-%d %H:%M:%S")
