"""Entidades e regras puras do domínio de custódia."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import uuid4


class TipoMovimentacao(StrEnum):
    RETENCAO = "RETENCAO"
    LIBERACAO = "LIBERACAO"
    DEVOLUCAO = "DEVOLUCAO"
    TAXA = "TAXA"


@dataclass(frozen=True)
class ContaCustodia:
    campanha_id: str
    meta: int
    prazo_fim: datetime
    saldo_retido: int = 0

    @classmethod
    def abrir(
        cls,
        campanha_id: str,
        meta: int,
        prazo_fim: datetime,
    ) -> ContaCustodia:
        if not campanha_id.strip():
            raise ValueError("campanha_id é obrigatório")
        if meta <= 0:
            raise ValueError("A meta deve ser positiva")
        if prazo_fim.tzinfo is None:
            raise ValueError("prazo_fim deve possuir fuso horário")

        return cls(
            campanha_id=campanha_id,
            meta=meta,
            prazo_fim=prazo_fim,
        )


@dataclass(frozen=True)
class Movimentacao:
    movimentacao_id: str
    campanha_id: str
    aporte_id: str | None
    tipo: TipoMovimentacao
    valor: int
    criada_em: datetime

    @classmethod
    def criar_retencao(
        cls,
        campanha_id: str,
        aporte_id: str,
        valor: int,
    ) -> Movimentacao:
        if not campanha_id.strip() or not aporte_id.strip():
            raise ValueError("Campanha e aporte são obrigatórios")
        if valor <= 0:
            raise ValueError("O valor da retenção deve ser positivo")

        return cls(
            movimentacao_id=str(uuid4()),
            campanha_id=campanha_id,
            aporte_id=aporte_id,
            tipo=TipoMovimentacao.RETENCAO,
            valor=valor,
            criada_em=datetime.now().astimezone(),
        )


def calcular_saldo(movimentacoes: tuple[Movimentacao, ...]) -> int:
    """Calcula o saldo a partir das movimentações registradas."""

    saldo = 0

    for movimentacao in movimentacoes:
        if movimentacao.tipo == TipoMovimentacao.RETENCAO:
            saldo += movimentacao.valor
        else:
            saldo -= movimentacao.valor

    if saldo < 0:
        raise ValueError("As movimentações não podem produzir saldo negativo")

    return saldo
