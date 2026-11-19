"""Testes da política de limite de aporte."""

from pathlib import Path

import pytest

from aportes.domain import Valor
from aportes.politica_limite_aporte import (
    PoliticaLimiteAporte,
    investidor_esta_verificado,
    validar_limite_aporte,
)
from aportes.repository import inicializar_banco
from shared.db import open_db


def test_aporte_abaixo_do_limite_sem_verificacao() -> None:
    politica = PoliticaLimiteAporte(limite_centavos=100_000)

    assert politica.permite(Valor(50_000), False)


def test_aporte_igual_ao_limite_sem_verificacao() -> None:
    politica = PoliticaLimiteAporte(limite_centavos=100_000)

    assert politica.permite(Valor(100_000), False)


def test_aporte_acima_do_limite_sem_verificacao() -> None:
    politica = PoliticaLimiteAporte(limite_centavos=100_000)

    assert not politica.permite(Valor(100_001), False)

    with pytest.raises(ValueError, match="investidor verificado"):
        politica.validar(Valor(100_001), False)


def test_aporte_acima_do_limite_com_verificacao() -> None:
    politica = PoliticaLimiteAporte(limite_centavos=100_000)

    assert politica.permite(Valor(150_000), True)
    politica.validar(Valor(150_000), True)


def test_limite_configurado_por_ambiente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIMITE_APORTE_CENTAVOS", "50000")

    politica = PoliticaLimiteAporte.from_env()

    assert politica.limite_centavos == 50_000


def test_limite_invalido_rejeitado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIMITE_APORTE_CENTAVOS", "invalido")

    with pytest.raises(ValueError):
        PoliticaLimiteAporte.from_env()


def test_sem_registro_rejeita_aporte_acima_do_limite(
    tmp_path: Path,
) -> None:
    inicializar_banco(tmp_path)

    assert not investidor_esta_verificado("usuario-1", tmp_path)

    with pytest.raises(ValueError, match="investidor verificado"):
        validar_limite_aporte(
            "usuario-1",
            Valor(150_000),
            tmp_path,
            PoliticaLimiteAporte(100_000),
        )


def test_registro_verificado_permite_aporte_acima_do_limite(
    tmp_path: Path,
) -> None:
    inicializar_banco(tmp_path)

    conn = open_db("aportes", tmp_path)

    try:
        conn.execute(
            """
            INSERT INTO investidor_verificado (investidor_id)
            VALUES (?)
            """,
            ("usuario-1",),
        )
        conn.commit()
    finally:
        conn.close()

    assert investidor_esta_verificado("usuario-1", tmp_path)

    validar_limite_aporte(
        "usuario-1",
        Valor(150_000),
        tmp_path,
        PoliticaLimiteAporte(100_000),
    )


def test_limite_negativo_rejeitado() -> None:
    with pytest.raises(ValueError):
        PoliticaLimiteAporte(-1)
