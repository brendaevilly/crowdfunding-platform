"""Consumidor dos eventos de cadastro para o módulo KYC."""

from __future__ import annotations

import sqlite3
from typing import Any

from contracts.eventos import UsuarioCadastrado
from identidade.kyc.servico import processar_usuario_cadastrado


def consumir_usuario_cadastrado(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> None:
    """Inicializa a verificação KYC de forma idempotente."""
    evento = UsuarioCadastrado.model_validate(payload)

    processar_usuario_cadastrado(
        conn,
        usuario_id=evento.usuario_id,
    )
