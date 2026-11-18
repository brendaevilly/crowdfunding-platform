"""Modelo de domínio do agregado Aporte."""

from dataclasses import dataclass, replace
from enum import StrEnum


@dataclass(frozen=True)
class Valor:
    """Valor monetário positivo, representado em centavos."""

    centavos: int

    def __post_init__(self) -> None:
        if isinstance(self.centavos, bool) or not isinstance(self.centavos, int):
            raise TypeError("O valor deve ser um número inteiro de centavos")

        if self.centavos <= 0:
            raise ValueError("O valor do aporte deve ser maior que zero")


class StatusAporte(StrEnum):
    PENDENTE = "PENDENTE"
    CONFIRMADO = "CONFIRMADO"
    REJEITADO = "REJEITADO"


@dataclass(frozen=True)
class Aporte:
    """Agregado raiz Aporte, com estado imutável."""

    id: str
    campanha_id: str
    investidor_id: str
    valor: Valor
    status: StatusAporte = StatusAporte.PENDENTE

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("O identificador do aporte é obrigatório")

        if not self.campanha_id.strip():
            raise ValueError("O identificador da campanha é obrigatório")

        if not self.investidor_id.strip():
            raise ValueError("O identificador do investidor é obrigatório")

        if not isinstance(self.valor, Valor):
            raise TypeError("O valor deve ser um objeto Valor")

        if not isinstance(self.status, StatusAporte):
            raise TypeError("Status do aporte inválido")

    def alterar_valor(self, novo_valor: Valor) -> "Aporte":
        """Altera o valor somente enquanto o aporte está pendente."""

        if self.status != StatusAporte.PENDENTE:
            raise ValueError("Não é possível alterar o valor de um aporte finalizado")

        if not isinstance(novo_valor, Valor):
            raise TypeError("O novo valor deve ser um objeto Valor")

        return replace(self, valor=novo_valor)

    def confirmar(self) -> "Aporte":
        """Confirma um aporte pendente."""

        if self.status != StatusAporte.PENDENTE:
            raise ValueError("Somente aportes pendentes podem ser confirmados")

        return replace(self, status=StatusAporte.CONFIRMADO)

    def rejeitar(self) -> "Aporte":
        """Rejeita um aporte pendente."""

        if self.status != StatusAporte.PENDENTE:
            raise ValueError("Somente aportes pendentes podem ser rejeitados")

        return replace(self, status=StatusAporte.REJEITADO)
