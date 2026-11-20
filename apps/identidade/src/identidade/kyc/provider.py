"""Contrato independente para provedores de verificação KYC."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from identidade.kyc.dominio import StatusVerificacao


@dataclass(frozen=True)
class ResultadoKyc:
    """Resultado devolvido por um provedor de identidade."""

    status: StatusVerificacao


class KycProvider(Protocol):
    """Interface que permite substituir o provedor sem alterar o KYC."""

    def verificar(self, *, tipo: str, numero: str) -> ResultadoKyc:
        """Avalia um documento sem persistir seu número original."""
        ...
