"""Testes de compatibilidade dos eventos com os contratos."""

import json
from datetime import UTC, datetime

import pytest

from contracts.catalogo import CATALOGO, ContratoInvalido, ler_envelope
from contracts.envelope import SCHEMA_VERSION_ATUAL
from contracts.eventos import (
    AporteConfirmado,
    CampanhaLiquidada,
    CampanhaPublicada,
    IdentidadeVerificada,
    Perfil,
    ResultadoCampanha,
    ResultadoFinal,
    RetornoDistribuido,
    StatusUsuario,
    TotalArrecadadoAtualizado,
    UsuarioCadastrado,
    UsuarioStatusAlterado,
)

AGORA = datetime.now(UTC)

PAYLOADS = {
    UsuarioCadastrado: {
        "usuario_id": "usuario-1",
        "perfil": Perfil.INVESTIDOR,
        "cadastrado_em": AGORA,
    },
    UsuarioStatusAlterado: {
        "usuario_id": "usuario-1",
        "status_anterior": StatusUsuario.ATIVO,
        "status_novo": StatusUsuario.BLOQUEADO,
        "alterado_em": AGORA,
    },
    IdentidadeVerificada: {
        "usuario_id": "usuario-1",
        "verificada_em": AGORA,
    },
    CampanhaPublicada: {
        "campanha_id": "campanha-1",
        "empreendedor_id": "usuario-1",
        "meta": 10000,
        "prazo_fim": AGORA,
    },
    TotalArrecadadoAtualizado: {
        "campanha_id": "campanha-1",
        "valor_acumulado": 5000,
    },
    AporteConfirmado: {
        "aporte_id": "aporte-1",
        "campanha_id": "campanha-1",
        "investidor_id": "usuario-2",
        "valor": 1000,
        "confirmado_em": AGORA,
    },
    CampanhaLiquidada: {
        "campanha_id": "campanha-1",
        "valor_bruto": 10000,
        "taxa_plataforma": 500,
        "valor_liquido": 9500,
        "liquidada_em": AGORA,
        "aportes": ("aporte-1",),
    },
    ResultadoCampanha: {
        "campanha_id": "campanha-1",
        "empreendedor_id": "usuario-1",
        "resultado": ResultadoFinal.SUCESSO,
        "valor_arrecadado": 10000,
        "investidor_ids": ("usuario-2",),
        "encerrada_em": AGORA,
    },
    RetornoDistribuido: {
        "retorno_id": "retorno-1",
        "campanha_id": "campanha-1",
        "investidor_id": "usuario-2",
        "valor": 1000,
        "evento_origem_id": "evento-1",
        "distribuido_em": AGORA,
    },
}


@pytest.mark.parametrize("modelo", list(PAYLOADS))
def test_produtor_gera_payload_valido_segundo_schema(modelo):
    payload = modelo.model_validate(PAYLOADS[modelo])

    assert isinstance(payload, modelo)


@pytest.mark.parametrize("topico", list(CATALOGO))
def test_consumidor_aceita_envelope_valido(topico):
    spec = CATALOGO[topico]
    payload = spec.payload.model_validate(PAYLOADS[spec.payload])

    bruto = {
        "eventId": "evento-teste",
        "topic": topico,
        "schemaVersion": SCHEMA_VERSION_ATUAL,
        "occurredAt": AGORA.isoformat(),
        "correlationId": "correlacao-teste",
        "payload": payload.model_dump(by_alias=True, mode="json"),
    }

    envelope = ler_envelope(json.dumps(bruto))

    assert envelope.topic == topico
    assert isinstance(envelope.payload, spec.payload)


@pytest.mark.parametrize("topico", list(CATALOGO))
def test_consumidor_rejeita_payload_invalido(topico):
    bruto = {
        "eventId": "evento-invalido",
        "topic": topico,
        "schemaVersion": SCHEMA_VERSION_ATUAL,
        "occurredAt": AGORA.isoformat(),
        "correlationId": "correlacao-teste",
        "payload": {},
    }

    with pytest.raises(ContratoInvalido):
        ler_envelope(json.dumps(bruto))


def test_consumidor_rejeita_topico_desconhecido():
    bruto = {
        "eventId": "evento-invalido",
        "topic": "topico.inexistente",
        "schemaVersion": SCHEMA_VERSION_ATUAL,
        "occurredAt": AGORA.isoformat(),
        "correlationId": "correlacao-teste",
        "payload": {},
    }

    with pytest.raises(ContratoInvalido):
        ler_envelope(json.dumps(bruto))


def test_consumidor_rejeita_versao_nao_suportada():
    bruto = {
        "eventId": "evento-invalido",
        "topic": next(iter(CATALOGO)),
        "schemaVersion": 999,
        "occurredAt": AGORA.isoformat(),
        "correlationId": "correlacao-teste",
        "payload": {},
    }

    with pytest.raises(ContratoInvalido):
        ler_envelope(json.dumps(bruto))
