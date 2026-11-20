"""Agregado VerificacaoIdentidade e regras de negócio do KYC."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum


class StatusVerificacao(StrEnum):
    """Estados possíveis de uma verificação de identidade."""

    PENDENTE = "PENDENTE"
    APROVADA = "APROVADA"
    REPROVADA = "REPROVADA"
    EXPIRADA = "EXPIRADA"


class VerificacaoInvalidaErro(ValueError):
    """Operação não permitida para o estado da verificação."""


@dataclass(frozen=True)
class VerificacaoIdentidade:
    """Agregado imutável que representa uma verificação KYC."""

    id: str
    usuario_id: str
    status: StatusVerificacao
    documento_tipo: str | None = None
    documento_hash: str | None = None
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None

    @classmethod
    def criar_pendente(
        cls,
        *,
        verificacao_id: str,
        usuario_id: str,
    ) -> VerificacaoIdentidade:
        """Cria uma verificação pendente para o usuário."""
        if not verificacao_id.strip() or not usuario_id.strip():
            raise VerificacaoInvalidaErro("IDs não podem ser vazios")

        agora = datetime.now(UTC)

        return cls(
            id=verificacao_id,
            usuario_id=usuario_id,
            status=StatusVerificacao.PENDENTE,
            criado_em=agora,
            atualizado_em=agora,
        )

    def registrar_documento(
        self,
        *,
        tipo: str,
        documento_hash: str,
    ) -> VerificacaoIdentidade:
        """Registra apenas o tipo e o hash do documento."""
        if self.status != StatusVerificacao.PENDENTE:
            raise VerificacaoInvalidaErro(
                "Documentos só podem ser registrados em verificações PENDENTES"
            )

        if not tipo.strip() or not documento_hash.strip():
            raise VerificacaoInvalidaErro("Tipo e hash são obrigatórios")

        return replace(
            self,
            documento_tipo=tipo,
            documento_hash=documento_hash,
            atualizado_em=datetime.now(UTC),
        )

    def aprovar(self) -> VerificacaoIdentidade:
        """Aprova uma verificação pendente."""
        if self.status != StatusVerificacao.PENDENTE:
            raise VerificacaoInvalidaErro("Somente verificações PENDENTES podem ser aprovadas")

        return replace(
            self,
            status=StatusVerificacao.APROVADA,
            atualizado_em=datetime.now(UTC),
        )

    def reprovar(self) -> VerificacaoIdentidade:
        """Reprova uma verificação pendente."""
        if self.status != StatusVerificacao.PENDENTE:
            raise VerificacaoInvalidaErro("Somente verificações PENDENTES podem ser reprovadas")

        return replace(
            self,
            status=StatusVerificacao.REPROVADA,
            atualizado_em=datetime.now(UTC),
        )

    def expirar(self) -> VerificacaoIdentidade:
        """Expira uma verificação pendente."""
        if self.status != StatusVerificacao.PENDENTE:
            raise VerificacaoInvalidaErro("Somente verificações PENDENTES podem expirar")

        return replace(
            self,
            status=StatusVerificacao.EXPIRADA,
            atualizado_em=datetime.now(UTC),
        )
