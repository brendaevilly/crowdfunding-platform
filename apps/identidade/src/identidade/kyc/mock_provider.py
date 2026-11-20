"""Provedor simulado para verificações de identidade."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from identidade.kyc.dominio import StatusVerificacao
from identidade.kyc.provider import ResultadoKyc


@dataclass(frozen=True)
class MockKycProvider:
    """Simula um terceiro responsável pela verificação de identidade."""

    atraso_segundos: float = 0.0

    def __post_init__(self) -> None:
        if self.atraso_segundos < 0:
            raise ValueError("O atraso do provedor KYC não pode ser negativo")

    def verificar(self, *, tipo: str, numero: str) -> ResultadoKyc:
        """Reprova CPF terminado em zero; aprova os demais documentos."""

        tipo_normalizado = tipo.strip().upper()
        numero_normalizado = "".join(caractere for caractere in numero if caractere.isalnum())

        if not tipo_normalizado or not numero_normalizado:
            raise ValueError("Tipo e número do documento são obrigatórios")

        if self.atraso_segundos:
            time.sleep(self.atraso_segundos)

        if tipo_normalizado == "CPF" and numero_normalizado.endswith("0"):
            return ResultadoKyc(status=StatusVerificacao.REPROVADA)

        return ResultadoKyc(status=StatusVerificacao.APROVADA)


def criar_mock_provider() -> MockKycProvider:
    """Cria o mock com atraso configurável pelo ambiente."""

    atraso = float(os.getenv("KYC_MOCK_DELAY_SECONDS", "0"))

    return MockKycProvider(atraso_segundos=atraso)
