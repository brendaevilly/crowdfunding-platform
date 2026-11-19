"""Payloads dos eventos (published language). O envelope fica em `envelope.py`."""

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, model_validator

from contracts.base import Centavos, CentavosPositivos, Contrato, Id


class Perfil(StrEnum):
    EMPREENDEDOR = "EMPREENDEDOR"
    INVESTIDOR = "INVESTIDOR"
    ADMIN = "ADMIN"


class StatusUsuario(StrEnum):
    ATIVO = "ATIVO"
    BLOQUEADO = "BLOQUEADO"


class ResultadoFinal(StrEnum):
    SUCESSO = "SUCESSO"
    FALHA = "FALHA"


class UsuarioCadastrado(Contrato):
    """Identidade -> Campanhas e KYC. Chave de idempotência: usuarioId."""

    usuario_id: Id
    perfil: Perfil
    cadastrado_em: AwareDatetime


class UsuarioStatusAlterado(Contrato):
    """LC-04 (novo). Identidade -> Campanhas e Aportes: bloqueio/desbloqueio de usuário."""

    usuario_id: Id
    status_anterior: StatusUsuario
    status_novo: StatusUsuario
    motivo: str | None = None
    alterado_em: AwareDatetime

    @model_validator(mode="after")
    def _status_mudou(self) -> UsuarioStatusAlterado:
        if self.status_anterior == self.status_novo:
            raise ValueError("statusNovo deve ser diferente de statusAnterior")
        return self


class IdentidadeVerificada(Contrato):
    """KYC -> Aportes (via ACL): o usuário passou na verificação de identidade."""

    usuario_id: Id
    verificada_em: AwareDatetime


class CampanhaPublicada(Contrato):
    """LC-01 (novo contrato). Campanhas -> Custódia: abre a ContaCustodia e agenda a apuração."""

    campanha_id: Id
    empreendedor_id: Id
    meta: CentavosPositivos
    prazo_fim: AwareDatetime


class TotalArrecadadoAtualizado(Contrato):
    """Custódia -> Campanhas. `valorAcumulado` é monotônico: ignore valor menor que o atual."""

    campanha_id: Id
    valor_acumulado: Centavos


class AporteConfirmado(Contrato):
    """Aportes -> Custódia: o aporte foi aceito e o valor deve ser retido."""

    aporte_id: Id
    campanha_id: Id
    investidor_id: Id
    valor: CentavosPositivos
    confirmado_em: AwareDatetime


class CampanhaLiquidada(Contrato):
    """Custódia -> Retornos. LC-06: emitido só no SUCESSO. LC-05: traz a taxa e o valor líquido."""

    campanha_id: Id
    valor_bruto: CentavosPositivos
    taxa_plataforma: Centavos
    valor_liquido: Centavos
    liquidada_em: AwareDatetime

    @model_validator(mode="after")
    def _bruto_igual_taxa_mais_liquido(self) -> CampanhaLiquidada:
        if self.valor_bruto != self.taxa_plataforma + self.valor_liquido:
            raise ValueError("valorBruto deve ser igual a taxaPlataforma + valorLiquido")
        return self


class ResultadoCampanha(Contrato):
    """LC-02. Custódia -> Campanhas e Notificação. Emitido em sucesso e em falha."""

    campanha_id: Id
    empreendedor_id: Id
    resultado: ResultadoFinal
    valor_arrecadado: Centavos
    investidor_ids: tuple[Id, ...]
    encerrada_em: AwareDatetime

    @model_validator(mode="after")
    def _investidores_unicos(self) -> ResultadoCampanha:
        if len(set(self.investidor_ids)) != len(self.investidor_ids):
            raise ValueError("investidorIds não pode ter repetidos")
        return self


class RetornoDistribuido(Contrato):
    """LC-02/LC-03. Retornos -> Notificação (substitui CampanhaLiquidada nesse contrato)."""

    retorno_id: Id
    campanha_id: Id
    investidor_id: Id
    valor: CentavosPositivos
    evento_origem_id: Id
    distribuido_em: AwareDatetime
