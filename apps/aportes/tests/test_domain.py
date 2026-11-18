"""Testes das regras de domínio de Aportes."""

from dataclasses import FrozenInstanceError

import pytest

from aportes.domain import Aporte, StatusAporte, Valor


def criar_aporte(valor: int = 2500) -> Aporte:
    return Aporte(
        id="aporte-1",
        campanha_id="campanha-1",
        investidor_id="investidor-1",
        valor=Valor(valor),
    )


@pytest.mark.parametrize("centavos", [0, -1, -100])
def test_valor_zero_ou_negativo_e_rejeitado(centavos: int) -> None:
    with pytest.raises(ValueError):
        Valor(centavos)


@pytest.mark.parametrize("centavos", [1.5, "2500", True])
def test_valor_deve_ser_inteiro(centavos: object) -> None:
    with pytest.raises(TypeError):
        Valor(centavos)  # type: ignore[arg-type]


def test_aporte_inicia_pendente() -> None:
    aporte = criar_aporte()

    assert aporte.status == StatusAporte.PENDENTE
    assert aporte.valor.centavos == 2500


def test_confirmar_aporte() -> None:
    confirmado = criar_aporte().confirmar()

    assert confirmado.status == StatusAporte.CONFIRMADO
    assert confirmado.valor.centavos == 2500


def test_rejeitar_aporte() -> None:
    rejeitado = criar_aporte().rejeitar()

    assert rejeitado.status == StatusAporte.REJEITADO


def test_alterar_valor_enquanto_pendente() -> None:
    original = criar_aporte()
    alterado = original.alterar_valor(Valor(5000))

    assert original.valor.centavos == 2500
    assert alterado.valor.centavos == 5000


def test_valor_nao_pode_mudar_apos_confirmacao() -> None:
    confirmado = criar_aporte().confirmar()

    with pytest.raises(ValueError):
        confirmado.alterar_valor(Valor(5000))


def test_valor_nao_pode_mudar_apos_rejeicao() -> None:
    rejeitado = criar_aporte().rejeitar()

    with pytest.raises(ValueError):
        rejeitado.alterar_valor(Valor(5000))


def test_atributos_sao_imutaveis() -> None:
    aporte = criar_aporte()

    with pytest.raises(FrozenInstanceError):
        aporte.valor = Valor(5000)  # type: ignore[misc]


def test_aporte_nao_pode_ser_confirmado_duas_vezes() -> None:
    confirmado = criar_aporte().confirmar()

    with pytest.raises(ValueError):
        confirmado.confirmar()


def test_aporte_rejeitado_nao_pode_ser_confirmado() -> None:
    rejeitado = criar_aporte().rejeitar()

    with pytest.raises(ValueError):
        rejeitado.confirmar()
