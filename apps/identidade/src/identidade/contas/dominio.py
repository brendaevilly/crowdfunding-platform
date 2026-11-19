"""Domínio do bounded context Contas (DDD Tático)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from contracts.eventos import Perfil


class StatusUsuario(StrEnum):
    PENDENTE = "PENDENTE"
    ATIVO = "ATIVO"
    BLOQUEADO = "BLOQUEADO"


_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


@dataclass(frozen=True)
class Email:
    """Value Object para validação e normalização de e-mails."""

    valor: str

    def __post_init__(self) -> None:
        bruto = self.valor.strip().lower()

        if not bruto or not _EMAIL_REGEX.match(bruto):
            raise ValueError(f"E-mail inválido: '{self.valor}'")

        object.__setattr__(self, "valor", bruto)

    def __str__(self) -> str:
        return self.valor


@dataclass(frozen=True)
class Usuario:
    """Entidade que representa uma conta de usuário."""

    id: str
    nome: str
    email: Email
    senha_hash: str
    perfil: Perfil
    status: StatusUsuario
    criado_em: datetime
    atualizado_em: datetime

    def ativar(self) -> Usuario:
        """Transiciona de PENDENTE para ATIVO."""

        if self.status == StatusUsuario.BLOQUEADO:
            raise ValueError("Usuário bloqueado não pode ser ativado diretamente")

        if self.status == StatusUsuario.ATIVO:
            return self

        agora = datetime.now(UTC)

        return Usuario(
            id=self.id,
            nome=self.nome,
            email=self.email,
            senha_hash=self.senha_hash,
            perfil=self.perfil,
            status=StatusUsuario.ATIVO,
            criado_em=self.criado_em,
            atualizado_em=agora,
        )

    def bloquear(self) -> Usuario:
        """Transiciona um usuário de ATIVO para BLOQUEADO."""

        if self.status != StatusUsuario.ATIVO:
            raise ValueError("Somente usuários ativos podem ser bloqueados")

        agora = datetime.now(UTC)

        return Usuario(
            id=self.id,
            nome=self.nome,
            email=self.email,
            senha_hash=self.senha_hash,
            perfil=self.perfil,
            status=StatusUsuario.BLOQUEADO,
            criado_em=self.criado_em,
            atualizado_em=agora,
        )

    def desbloquear(self) -> Usuario:
        """Transiciona um usuário de BLOQUEADO para ATIVO."""

        if self.status != StatusUsuario.BLOQUEADO:
            raise ValueError("Somente usuários bloqueados podem ser desbloqueados")

        agora = datetime.now(UTC)

        return Usuario(
            id=self.id,
            nome=self.nome,
            email=self.email,
            senha_hash=self.senha_hash,
            perfil=self.perfil,
            status=StatusUsuario.ATIVO,
            criado_em=self.criado_em,
            atualizado_em=agora,
        )
