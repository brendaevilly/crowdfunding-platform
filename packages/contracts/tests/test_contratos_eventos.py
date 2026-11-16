from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from contracts import (
    AporteConfirmado,
    CampanhaLiquidada,
    CampanhaPublicada,
    IdentidadeVerificada,
    ResultadoCampanha,
    ResultadoFinal,
    RetornoDistribuido,
    StatusUsuario,
    TotalArrecadadoAtualizado,
    UsuarioStatusAlterado,
)
from contracts.exemplos import AGORA, exemplos


@pytest.mark.parametrize("evento", exemplos(), ids=lambda e: type(e).__name__)
def test_json_em_camel_case_e_round_trip(evento: Any) -> None:
    dados = evento.para_dict()
    assert all("_" not in chave for chave in dados), dados
    assert type(evento).model_validate(dados) == evento
    assert type(evento).model_validate_json(evento.para_json()) == evento


@pytest.mark.parametrize("evento", exemplos(), ids=lambda e: type(e).__name__)
def test_imutavel_e_sem_campos_extras(evento: Any) -> None:
    primeiro = next(iter(type(evento).model_fields))
    with pytest.raises(ValidationError):
        setattr(evento, primeiro, "x")
    with pytest.raises(ValidationError):
        type(evento).model_validate({**evento.para_dict(), "campoNovo": 1})


def test_lc01_campanha_publicada_tem_os_campos_do_contrato() -> None:
    campos = set(CampanhaPublicada.model_fields)
    assert campos == {"campanha_id", "empreendedor_id", "meta", "prazo_fim"}


def test_lc02_resultado_traz_destinatarios_e_retorno_traz_investidor() -> None:
    assert {"empreendedor_id", "investidor_ids"} <= set(ResultadoCampanha.model_fields)
    assert "investidor_id" in RetornoDistribuido.model_fields


def test_resultado_rejeita_investidores_repetidos() -> None:
    with pytest.raises(ValidationError, match="repetidos"):
        ResultadoCampanha(
            campanha_id="c1",
            empreendedor_id="e1",
            resultado=ResultadoFinal.FALHA,
            valor_arrecadado=0,
            investidor_ids=("u1", "u1"),
            encerrada_em=AGORA,
        )


def test_lc04_status_precisa_mudar() -> None:
    with pytest.raises(ValidationError, match="diferente"):
        UsuarioStatusAlterado(
            usuario_id="u1",
            status_anterior=StatusUsuario.ATIVO,
            status_novo=StatusUsuario.ATIVO,
            alterado_em=AGORA,
        )


def test_lc05_bruto_igual_taxa_mais_liquido() -> None:
    with pytest.raises(ValidationError, match="taxaPlataforma"):
        CampanhaLiquidada(
            campanha_id="c1",
            valor_bruto=1_000,
            taxa_plataforma=50,
            valor_liquido=900,
            liquidada_em=AGORA,
        )


def test_valores_monetarios_sao_inteiros_positivos() -> None:
    with pytest.raises(ValidationError):
        AporteConfirmado(
            aporte_id="a", campanha_id="c", investidor_id="u", valor=0, confirmado_em=AGORA
        )
    with pytest.raises(ValidationError):
        AporteConfirmado.model_validate(
            {
                "aporteId": "a",
                "campanhaId": "c",
                "investidorId": "u",
                "valor": 10.5,
                "confirmadoEm": AGORA.isoformat(),
            }
        )


def test_datas_exigem_fuso() -> None:
    with pytest.raises(ValidationError):
        IdentidadeVerificada(usuario_id="u1", verificada_em=datetime(2026, 1, 1))


def test_ids_nao_podem_ser_vazios() -> None:
    with pytest.raises(ValidationError):
        TotalArrecadadoAtualizado(campanha_id="  ", valor_acumulado=1)
