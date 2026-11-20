"""Objetos de valor, máquina de estados e agregado Campanha."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


class StatusCampanha(StrEnum):
    """Estados possíveis do ciclo de vida de uma campanha."""

    RASCUNHO = "RASCUNHO"
    EM_MODERACAO = "EM_MODERACAO"
    PUBLICADA = "PUBLICADA"
    REPROVADA = "REPROVADA"
    ENCERRADA = "ENCERRADA"
    CANCELADA = "CANCELADA"


class TransicaoInvalidaError(ValueError):
    """Tentativa de transição não permitida na máquina de estados."""


class ConcorrenciaOtimistaError(RuntimeError):
    """Conflito de versão em atualização concorrente."""


@dataclass(frozen=True)
class Meta:
    """Valor monetário da meta da campanha em centavos (positivo)."""

    centavos: int

    def __post_init__(self) -> None:
        if self.centavos <= 0:
            raise ValueError("A meta deve ser maior que zero (em centavos).")


@dataclass(frozen=True)
class Prazo:
    """Período de vigência da campanha (fim estritamente após início)."""

    inicio: datetime
    fim: datetime

    def __post_init__(self) -> None:
        if self.fim <= self.inicio:
            raise ValueError("O prazo final deve ser posterior ao prazo inicial.")


@dataclass
class Campanha:
    """Agregado raiz Campanha com controle de concorrência otimista."""

    id: str
    empreendedor_id: str
    titulo: str
    descricao: str
    meta: Meta
    prazo: Prazo
    status: StatusCampanha = StatusCampanha.RASCUNHO
    valor_arrecadado: int = 0
    motivo_reprovacao: str | None = None
    versao: int = 1
    criado_em: datetime = field(default_factory=lambda: datetime.now(UTC))
    atualizado_em: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def meta_atingida(self) -> bool:
        """Indica se o valor arrecadado atingiu ou superou a meta."""
        return self.valor_arrecadado >= self.meta.centavos

    def esta_dentro_do_prazo(self, agora: datetime | None = None) -> bool:
        """Verifica se a campanha ainda está dentro do período de vigência."""
        agora_ref = agora or datetime.now(UTC)
        return agora_ref <= self.prazo.fim

    def aceita_aportes(self, agora: datetime | None = None) -> bool:
        """Regra 2: aceita aportes apenas se estiver PUBLICADA e dentro do prazo."""
        return self.status == StatusCampanha.PUBLICADA and self.esta_dentro_do_prazo(agora)

    @classmethod
    def criar(
        cls,
        *,
        empreendedor_id: str,
        titulo: str,
        descricao: str,
        meta: int,
        prazo_inicio: datetime,
        prazo_fim: datetime,
        campanha_id: str | None = None,
    ) -> Campanha:
        """Cria uma nova campanha no estado RASCUNHO."""
        titulo_limpo = titulo.strip()
        descricao_limpa = descricao.strip()
        if not titulo_limpo:
            raise ValueError("O título não pode ser vazio.")
        if not descricao_limpa:
            raise ValueError("A descrição não pode ser vazia.")

        vo_meta = Meta(meta)
        vo_prazo = Prazo(prazo_inicio, prazo_fim)
        cid = campanha_id or str(uuid4())
        agora = datetime.now(UTC)

        return cls(
            id=cid,
            empreendedor_id=empreendedor_id,
            titulo=titulo_limpo,
            descricao=descricao_limpa,
            meta=vo_meta,
            prazo=vo_prazo,
            status=StatusCampanha.RASCUNHO,
            valor_arrecadado=0,
            motivo_reprovacao=None,
            versao=1,
            criado_em=agora,
            atualizado_em=agora,
        )

    def editar(
        self,
        *,
        titulo: str,
        descricao: str,
        meta: int,
        prazo_inicio: datetime,
        prazo_fim: datetime,
        versao_esperada: int | None = None,
    ) -> None:
        """Edição permitida somente quando a campanha estiver em RASCUNHO."""
        if self.status != StatusCampanha.RASCUNHO:
            raise TransicaoInvalidaError(
                f"Campanha no status {self.status.value} não pode ser editada; "
                "apenas campanhas em RASCUNHO podem ser modificadas."
            )

        if versao_esperada is not None and versao_esperada != self.versao:
            raise ConcorrenciaOtimistaError(
                f"Versão informada ({versao_esperada}) não confere com a versão "
                f"atual ({self.versao})."
            )

        titulo_limpo = titulo.strip()
        descricao_limpa = descricao.strip()
        if not titulo_limpo:
            raise ValueError("O título não pode ser vazio.")
        if not descricao_limpa:
            raise ValueError("A descrição não pode ser vazia.")

        self.titulo = titulo_limpo
        self.descricao = descricao_limpa
        self.meta = Meta(meta)
        self.prazo = Prazo(prazo_inicio, prazo_fim)
        self.versao += 1
        self.atualizado_em = datetime.now(UTC)

    def submeter(self) -> None:
        """Transição de RASCUNHO para EM_MODERACAO."""
        if self.status != StatusCampanha.RASCUNHO:
            raise TransicaoInvalidaError(
                f"Apenas campanhas em RASCUNHO podem ser submetidas para moderação "
                f"(status atual: {self.status.value})."
            )
        self.status = StatusCampanha.EM_MODERACAO
        self.versao += 1
        self.atualizado_em = datetime.now(UTC)

    def aprovar(self) -> None:
        """Transição de EM_MODERACAO para PUBLICADA."""
        if self.status == StatusCampanha.REPROVADA:
            raise TransicaoInvalidaError(
                "Campanha REPROVADA nunca pode ser aprovada ou reativada (Regra 9)."
            )
        if self.status != StatusCampanha.EM_MODERACAO:
            raise TransicaoInvalidaError(
                f"Apenas campanhas em EM_MODERACAO podem ser aprovadas "
                f"(status atual: {self.status.value})."
            )
        self.status = StatusCampanha.PUBLICADA
        self.versao += 1
        self.atualizado_em = datetime.now(UTC)

    def reprovar(self, motivo: str) -> None:
        """Transição de EM_MODERACAO para REPROVADA com motivo obrigatório."""
        motivo_limpo = motivo.strip() if motivo else ""
        if not motivo_limpo:
            raise ValueError("O motivo da reprovação é obrigatório.")
        if self.status != StatusCampanha.EM_MODERACAO:
            raise TransicaoInvalidaError(
                f"Apenas campanhas em EM_MODERACAO podem ser reprovadas "
                f"(status atual: {self.status.value})."
            )
        self.status = StatusCampanha.REPROVADA
        self.motivo_reprovacao = motivo_limpo
        self.versao += 1
        self.atualizado_em = datetime.now(UTC)
