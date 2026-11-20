"""Testes unitários do agregado Campanha e seus Value Objects."""

from datetime import UTC, datetime, timedelta

import pytest

from campanhas.domain import (
    Campanha,
    ConcorrenciaOtimistaError,
    Meta,
    Prazo,
    StatusCampanha,
    TransicaoInvalidaError,
)


def test_meta_valor_positivo() -> None:
    meta = Meta(500000)
    assert meta.centavos == 500000


@pytest.mark.parametrize("valor", [0, -1, -5000])
def test_meta_valor_invalido_dispara_erro(valor: int) -> None:
    with pytest.raises(ValueError, match="maior que zero"):
        Meta(valor)


def test_prazo_valido() -> None:
    inicio = datetime.now(UTC)
    fim = inicio + timedelta(days=30)
    prazo = Prazo(inicio, fim)
    assert prazo.inicio == inicio
    assert prazo.fim == fim


def test_prazo_invalido_fim_anterior_ou_igual_a_inicio() -> None:
    agora = datetime.now(UTC)
    with pytest.raises(ValueError, match="posterior ao prazo inicial"):
        Prazo(agora, agora)

    with pytest.raises(ValueError, match="posterior ao prazo inicial"):
        Prazo(agora, agora - timedelta(days=1))


def test_criar_campanha_estado_inicial() -> None:
    inicio = datetime.now(UTC)
    fim = inicio + timedelta(days=45)
    campanha = Campanha.criar(
        empreendedor_id="emp-1",
        titulo="Projeto Solar",
        descricao="Energia limpa para comunidades",
        meta=1000000,
        prazo_inicio=inicio,
        prazo_fim=fim,
    )

    assert campanha.id is not None
    assert campanha.empreendedor_id == "emp-1"
    assert campanha.titulo == "Projeto Solar"
    assert campanha.descricao == "Energia limpa para comunidades"
    assert campanha.meta.centavos == 1000000
    assert campanha.status == StatusCampanha.RASCUNHO
    assert campanha.valor_arrecadado == 0
    assert campanha.versao == 1
    assert campanha.motivo_reprovacao is None


@pytest.mark.parametrize("titulo,descricao", [("", "valido"), ("valido", ""), ("   ", "valido")])
def test_criar_campanha_campos_vazios(titulo: str, descricao: str) -> None:
    inicio = datetime.now(UTC)
    fim = inicio + timedelta(days=10)
    with pytest.raises(ValueError):
        Campanha.criar(
            empreendedor_id="emp-1",
            titulo=titulo,
            descricao=descricao,
            meta=10000,
            prazo_inicio=inicio,
            prazo_fim=fim,
        )


def test_editar_campanha_em_rascunho_sucesso() -> None:
    inicio = datetime.now(UTC)
    fim = inicio + timedelta(days=20)
    campanha = Campanha.criar(
        empreendedor_id="emp-1",
        titulo="Original",
        descricao="Original",
        meta=10000,
        prazo_inicio=inicio,
        prazo_fim=fim,
    )

    novo_fim = fim + timedelta(days=10)
    campanha.editar(
        titulo="Editado",
        descricao="Descricao Nova",
        meta=20000,
        prazo_inicio=inicio,
        prazo_fim=novo_fim,
        versao_esperada=1,
    )

    assert campanha.titulo == "Editado"
    assert campanha.descricao == "Descricao Nova"
    assert campanha.meta.centavos == 20000
    assert campanha.versao == 2


def test_editar_campanha_versao_incompativel_dispara_concorrencia() -> None:
    inicio = datetime.now(UTC)
    fim = inicio + timedelta(days=20)
    campanha = Campanha.criar(
        empreendedor_id="emp-1",
        titulo="Original",
        descricao="Original",
        meta=10000,
        prazo_inicio=inicio,
        prazo_fim=fim,
    )

    with pytest.raises(ConcorrenciaOtimistaError, match="não confere"):
        campanha.editar(
            titulo="Concorrente",
            descricao="Nova",
            meta=15000,
            prazo_inicio=inicio,
            prazo_fim=fim,
            versao_esperada=99,
        )


@pytest.mark.parametrize(
    "status_nao_rascunho",
    [
        StatusCampanha.EM_MODERACAO,
        StatusCampanha.PUBLICADA,
        StatusCampanha.REPROVADA,
        StatusCampanha.ENCERRADA,
        StatusCampanha.CANCELADA,
    ],
)
def test_editar_campanha_fora_de_rascunho_rejeitada(
    status_nao_rascunho: StatusCampanha,
) -> None:
    inicio = datetime.now(UTC)
    fim = inicio + timedelta(days=20)
    campanha = Campanha.criar(
        empreendedor_id="emp-1",
        titulo="Original",
        descricao="Original",
        meta=10000,
        prazo_inicio=inicio,
        prazo_fim=fim,
    )
    campanha.status = status_nao_rascunho

    with pytest.raises(TransicaoInvalidaError, match="apenas campanhas em RASCUNHO"):
        campanha.editar(
            titulo="Novo",
            descricao="Novo",
            meta=15000,
            prazo_inicio=inicio,
            prazo_fim=fim,
            versao_esperada=1,
        )
