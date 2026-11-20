"""Testes do contrato e da implementação mock do provedor KYC."""

from __future__ import annotations

import pytest

from identidade.kyc.dominio import StatusVerificacao
from identidade.kyc.mock_provider import MockKycProvider, criar_mock_provider
from identidade.kyc.provider import KycProvider, ResultadoKyc


def test_mock_aprova_documento_valido() -> None:
    provider = MockKycProvider()

    resultado = provider.verificar(
        tipo="CPF",
        numero="12345678909",
    )

    assert resultado.status == StatusVerificacao.APROVADA


def test_mock_reprova_cpf_terminado_em_zero() -> None:
    provider = MockKycProvider()

    resultado = provider.verificar(
        tipo="CPF",
        numero="12345678900",
    )

    assert resultado.status == StatusVerificacao.REPROVADA


def test_mock_permite_configurar_atraso_zero() -> None:
    provider = MockKycProvider(atraso_segundos=0.0)

    assert provider.atraso_segundos == 0.0


def test_mock_rejeita_atraso_negativo() -> None:
    with pytest.raises(ValueError):
        MockKycProvider(atraso_segundos=-1.0)


def test_atraso_pode_ser_configurado_por_ambiente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KYC_MOCK_DELAY_SECONDS", "0.25")

    provider = criar_mock_provider()

    assert provider.atraso_segundos == 0.25


def test_provider_pode_ser_substituido() -> None:
    class ProviderAlternativo:
        def verificar(self, *, tipo: str, numero: str) -> ResultadoKyc:
            return ResultadoKyc(status=StatusVerificacao.REPROVADA)

    provider: KycProvider = ProviderAlternativo()

    resultado = provider.verificar(
        tipo="CPF",
        numero="12345678909",
    )

    assert resultado.status == StatusVerificacao.REPROVADA
