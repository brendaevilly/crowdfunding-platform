from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from contracts import (
    CATALOGO,
    SCHEMA_VERSION_ATUAL,
    CampanhaLiquidada,
    CampanhaStatusResponse,
    ContratoInvalido,
    ResultadoCampanha,
    RetornoDistribuido,
    StatusCampanha,
    caminho_status_campanha,
    chave_idempotencia,
    criar_envelope,
    ler_envelope,
    topicos,
)
from contracts.exemplos import AGORA, exemplos


def test_catalogo_cobre_exatamente_os_topicos() -> None:
    assert set(CATALOGO) == set(topicos.TODOS)
    assert len(topicos.TODOS) == len(set(topicos.TODOS))
    assert len(CATALOGO) == 9


@pytest.mark.parametrize("evento", exemplos(), ids=lambda e: type(e).__name__)
def test_envelope_round_trip_para_todo_evento(evento: Any) -> None:
    env = criar_envelope(evento, correlation_id="cid-1", event_id="ev-1", occurred_at=AGORA)
    lido = ler_envelope(env.para_json())
    assert lido.payload == evento
    assert lido.topic == CATALOGO[lido.topic].topico
    assert (lido.event_id, lido.correlation_id, lido.schema_version) == (
        "ev-1",
        "cid-1",
        SCHEMA_VERSION_ATUAL,
    )
    assert ler_envelope(env.para_dict()).payload == evento


def test_criar_envelope_gera_id_e_data() -> None:
    env = criar_envelope(exemplos()[0], correlation_id="c")
    assert len(env.event_id) == 32
    assert abs((datetime.now(UTC) - env.occurred_at).total_seconds()) < 5


def test_json_do_envelope_usa_camel_case() -> None:
    bruto = json.loads(criar_envelope(exemplos()[0], correlation_id="c").para_json())
    assert set(bruto) == {
        "eventId",
        "topic",
        "schemaVersion",
        "occurredAt",
        "correlationId",
        "payload",
    }
    assert bruto["topic"] == topicos.USUARIO_CADASTRADO


@pytest.mark.parametrize(
    ("alteracao", "trecho"),
    [
        ({"topic": "nao.existe"}, "tópico desconhecido"),
        ({"schemaVersion": 99}, "não suportado"),
        ({"schemaVersion": None}, "não suportado"),
        ({"payload": {"usuarioId": "u1"}}, "perfil"),
    ],
)
def test_ler_envelope_rejeita_mensagem_invalida(alteracao: dict[str, Any], trecho: str) -> None:
    bruto = criar_envelope(exemplos()[0], correlation_id="c").para_dict()
    bruto.update(alteracao)
    with pytest.raises(ContratoInvalido, match=trecho):
        ler_envelope(bruto)


def test_ler_envelope_rejeita_json_quebrado() -> None:
    with pytest.raises(ContratoInvalido, match="JSON"):
        ler_envelope("{nao e json")


def test_criar_envelope_rejeita_payload_fora_do_catalogo() -> None:
    with pytest.raises(ContratoInvalido):
        criar_envelope(
            CampanhaStatusResponse(campanha_id="c", status=StatusCampanha.PUBLICADA),
            correlation_id="c",
        )


def _env(indice: int) -> Any:
    return criar_envelope(exemplos()[indice], correlation_id="c", event_id="ev-9")


def test_chaves_de_idempotencia() -> None:
    chaves = {
        type(e).__name__: chave_idempotencia(criar_envelope(e, correlation_id="c", event_id="ev-9"))
        for e in exemplos()
    }
    assert chaves == {
        "UsuarioCadastrado": "u1",
        "UsuarioStatusAlterado": "ev-9",
        "IdentidadeVerificada": "u1",
        "CampanhaPublicada": "c1",
        "TotalArrecadadoAtualizado": "ev-9",
        "AporteConfirmado": "a1",
        "CampanhaLiquidada": "c1",
        "ResultadoCampanha": "c1",
        "RetornoDistribuido": "u1:ev1",
    }


def test_todo_evento_documenta_produtor_consumidores_e_chave() -> None:
    for spec in CATALOGO.values():
        assert spec.produtor
        assert spec.consumidores
        assert spec.chave_idempotencia


def test_lc03_notificacao_consome_retorno_e_nao_campanha_liquidada() -> None:
    consumidores = {spec.payload: set(spec.consumidores) for spec in CATALOGO.values()}
    assert "notificacao" in consumidores[RetornoDistribuido]
    assert "notificacao" in consumidores[ResultadoCampanha]
    assert "notificacao" not in consumidores[CampanhaLiquidada]


def test_endpoint_sincrono_de_status() -> None:
    assert caminho_status_campanha("c1") == "/campanhas/c1/status"
    resp = CampanhaStatusResponse.model_validate({"campanhaId": "c1", "status": "PUBLICADA"})
    assert resp.aceita_aportes is True
    assert resp.para_dict() == {"campanhaId": "c1", "status": "PUBLICADA"}
    rascunho = CampanhaStatusResponse(campanha_id="c1", status=StatusCampanha.RASCUNHO)
    assert rascunho.aceita_aportes is False
