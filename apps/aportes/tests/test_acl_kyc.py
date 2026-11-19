"""Testes da ACL entre KYC e Aportes."""

import sqlite3

import pytest

from aportes.acl_kyc import (
    consumir_identidade_verificada,
    traduzir_identidade_verificada,
)


def payload_valido() -> dict[str, str]:
    return {
        "usuarioId": "investidor-123",
        "verificadaEm": "2026-11-18T12:00:00Z",
    }


def test_traducao_identidade_verificada() -> None:
    investidor = traduzir_identidade_verificada(payload_valido())

    assert investidor.usuario_id == "investidor-123"
    assert investidor.verificado is True
    assert set(vars(investidor)) == {"usuario_id", "verificado"}


def test_traducao_rejeita_evento_invalido() -> None:
    with pytest.raises(ValueError):
        traduzir_identidade_verificada({"usuarioId": "investidor-123"})


def test_consumo_idempotente_por_usuario_id() -> None:
    conn = sqlite3.connect(":memory:")

    try:
        conn.execute(
            """
            CREATE TABLE investidor_verificado (
                investidor_id TEXT PRIMARY KEY,
                verificado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        consumir_identidade_verificada(conn, payload_valido())
        consumir_identidade_verificada(conn, payload_valido())

        quantidade = conn.execute(
            """
            SELECT COUNT(*)
            FROM investidor_verificado
            WHERE investidor_id = ?
            """,
            ("investidor-123",),
        ).fetchone()

        assert quantidade is not None
        assert quantidade[0] == 1

    finally:
        conn.close()
