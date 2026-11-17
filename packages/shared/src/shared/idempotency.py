
"""Controle de idempotência para consumidores de eventos."""

import sqlite3
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def consume_once(
    chave: str,
    tx: sqlite3.Connection,
    fn: Callable[[sqlite3.Connection], T],
) -> tuple[bool, T | None]:
    """Executa um efeito de negócio uma única vez por chave.

    A conexão deve estar dentro de uma transação externa.

    Retorna:
        (True, resultado) quando o evento foi processado.
        (False, None) quando o evento já foi processado.
    """
    if not chave:
        raise ValueError("A chave de idempotência não pode ser vazia")

    cursor = tx.execute(
        """
        INSERT INTO evento_processado (chave)
        VALUES (?)
        ON CONFLICT(chave) DO NOTHING
        """,
        (chave,),
    )

    if cursor.rowcount == 0:
        return False, None

    resultado = fn(tx)
    return True, resultado


def consumeOnce(
    chave: str,
    tx: sqlite3.Connection,
    fn: Callable[[sqlite3.Connection], T],
) -> tuple[bool, T | None]:
    """Alias compatível com o nome solicitado na issue."""
    return consume_once(chave, tx, fn)
