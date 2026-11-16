"""Catálogo dos eventos: tópico, produtor, consumidores e chave de idempotência.

É a fonte única usada pelos serviços (publicar/ler) e pela documentação gerada
(`scripts/gen_contratos_doc.py` -> docs/contratos).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from pydantic import ValidationError

from contracts import topicos
from contracts.base import Contrato
from contracts.envelope import SCHEMA_VERSION_ATUAL, Envelope
from contracts.eventos import (
    AporteConfirmado,
    CampanhaLiquidada,
    CampanhaPublicada,
    IdentidadeVerificada,
    ResultadoCampanha,
    RetornoDistribuido,
    TotalArrecadadoAtualizado,
    UsuarioCadastrado,
    UsuarioStatusAlterado,
)


class ContratoInvalido(ValueError):
    """Mensagem fora do contrato (tópico/versão desconhecidos ou payload inválido)."""


@dataclass(frozen=True)
class EventoSpec:
    topico: str
    payload: type[Contrato]
    produtor: str
    consumidores: Mapping[str, str]  # consumidor -> efeito
    chave_idempotencia: str  # descrição legível (vai para a documentação)
    chave: Callable[[Envelope[Any]], str]  # valor usado em evento_processado.chave

    @property
    def versoes(self) -> Mapping[int, type[Contrato]]:
        return {SCHEMA_VERSION_ATUAL: self.payload}


def _spec(
    topico: str,
    payload: type[Contrato],
    produtor: str,
    consumidores: Mapping[str, str],
    descricao: str,
    chave: Callable[[Envelope[Any]], str],
) -> EventoSpec:
    return EventoSpec(topico, payload, produtor, consumidores, descricao, chave)


_ESPECIFICACOES = (
    _spec(
        topicos.USUARIO_CADASTRADO,
        UsuarioCadastrado,
        "identidade (contas)",
        {
            "campanhas": "cria a projeção local do usuário",
            "identidade (kyc)": "abre a verificação de identidade",
        },
        "usuarioId",
        lambda e: e.payload.usuario_id,
    ),
    _spec(
        topicos.USUARIO_STATUS_ALTERADO,
        UsuarioStatusAlterado,
        "identidade (contas)",
        {
            "campanhas": "bloqueia/libera a publicação de campanhas (cada evento é uma transição)",
            "aportes": "bloqueia/libera novos aportes",
        },
        "eventId",
        lambda e: e.event_id,
    ),
    _spec(
        topicos.IDENTIDADE_VERIFICADA,
        IdentidadeVerificada,
        "identidade (kyc)",
        {"aportes": "marca o investidor como verificado (via camada anticorrupção)"},
        "usuarioId",
        lambda e: e.payload.usuario_id,
    ),
    _spec(
        topicos.CAMPANHA_PUBLICADA,
        CampanhaPublicada,
        "campanhas",
        {"custodia_retornos (custódia)": "abre a ContaCustodia e agenda a apuração em prazoFim"},
        "campanhaId",
        lambda e: e.payload.campanha_id,
    ),
    _spec(
        topicos.TOTAL_ARRECADADO_ATUALIZADO,
        TotalArrecadadoAtualizado,
        "custodia_retornos (custódia)",
        {"campanhas": "atualiza valorAcumulado (monotônico: ignora valor menor que o atual)"},
        "eventId",
        lambda e: e.event_id,
    ),
    _spec(
        topicos.APORTE_CONFIRMADO,
        AporteConfirmado,
        "aportes",
        {"custodia_retornos (custódia)": "registra a RETENCAO do valor na ContaCustodia"},
        "aporteId",
        lambda e: e.payload.aporte_id,
    ),
    _spec(
        topicos.CAMPANHA_LIQUIDADA,
        CampanhaLiquidada,
        "custodia_retornos (custódia)",
        {"custodia_retornos (retornos)": "calcula e distribui os retornos aos investidores"},
        "campanhaId",
        lambda e: e.payload.campanha_id,
    ),
    _spec(
        topicos.RESULTADO_CAMPANHA,
        ResultadoCampanha,
        "custodia_retornos (custódia)",
        {
            "campanhas": "encerra a campanha com o resultado",
            "notificacao": "avisa o empreendedor e os investidores",
        },
        "campanhaId",
        lambda e: e.payload.campanha_id,
    ),
    _spec(
        topicos.RETORNO_DISTRIBUIDO,
        RetornoDistribuido,
        "custodia_retornos (retornos)",
        {"notificacao": "avisa o investidor do retorno recebido"},
        "(investidorId, eventoOrigemId)",
        lambda e: f"{e.payload.investidor_id}:{e.payload.evento_origem_id}",
    ),
)

CATALOGO: Mapping[str, EventoSpec] = {s.topico: s for s in _ESPECIFICACOES}
TOPICO_DO_PAYLOAD: Mapping[type[Contrato], str] = {s.payload: s.topico for s in _ESPECIFICACOES}


def criar_envelope[P: Contrato](
    payload: P,
    *,
    correlation_id: str,
    event_id: str | None = None,
    occurred_at: datetime | None = None,
) -> Envelope[P]:
    """Monta o envelope de um payload do catálogo (tópico e versão saem do catálogo)."""
    topico = TOPICO_DO_PAYLOAD.get(type(payload))
    if topico is None:
        raise ContratoInvalido(f"{type(payload).__name__} não está no catálogo")
    return Envelope[Any](
        event_id=event_id or uuid4().hex,
        topic=topico,
        schema_version=SCHEMA_VERSION_ATUAL,
        occurred_at=occurred_at or datetime.now(UTC),
        correlation_id=correlation_id,
        payload=payload,
    )


def ler_envelope(bruto: str | bytes | Mapping[str, Any]) -> Envelope[Any]:
    """Valida uma mensagem recebida: tópico, versão e payload contra o catálogo."""
    try:
        dados = dict(json.loads(bruto) if isinstance(bruto, str | bytes) else bruto)
    except (ValueError, TypeError) as exc:
        raise ContratoInvalido(f"JSON inválido: {exc}") from exc
    spec = CATALOGO.get(str(dados.get("topic")))
    if spec is None:
        raise ContratoInvalido(f"tópico desconhecido: {dados.get('topic')!r}")
    versao = dados.get("schemaVersion", dados.get("schema_version"))
    modelo = spec.versoes.get(versao) if isinstance(versao, int) else None
    if modelo is None:
        raise ContratoInvalido(
            f"schemaVersion {versao!r} não suportado para {spec.topico} "
            f"(suportadas: {sorted(spec.versoes)})"
        )
    try:
        return cast(
            Envelope[Any],
            Envelope[modelo].model_validate(dados),  # type: ignore[valid-type]
        )
    except ValidationError as exc:
        raise ContratoInvalido(str(exc)) from exc


def chave_idempotencia(envelope: Envelope[Any]) -> str:
    """Valor da chave única para `evento_processado` (mesmo cálculo em todo consumidor)."""
    return CATALOGO[envelope.topic].chave(envelope)
