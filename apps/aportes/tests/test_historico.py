"""Testes dos endpoints de histórico e resumo de aportes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aportes.api import criar_router
from aportes.domain import Aporte, StatusAporte, Valor
from aportes.repository import AporteRepository, inicializar_banco
from shared.auth import emitir_token, segredo_do_ambiente
from shared.http.app import create_app


def autenticar_investidor(investidor_id: str) -> dict[str, str]:
    """Gera um JWT válido para os testes de histórico."""
    segredo, _ = segredo_do_ambiente()

    token = emitir_token(
        sub=investidor_id,
        perfil="INVESTIDOR",
        segredo=segredo,
    )

    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ambiente(tmp_path: Path) -> tuple[TestClient, Path]:
    """Prepara API e banco isolados para cada teste."""
    inicializar_banco(tmp_path)

    app = create_app("aportes-teste")
    app.include_router(criar_router(data_dir=tmp_path))

    repositorio = AporteRepository(tmp_path)

    registros = [
        ("aporte-1", "campanha-1", "investidor-A", 1000, StatusAporte.CONFIRMADO),
        ("aporte-2", "campanha-1", "investidor-A", 2000, StatusAporte.CONFIRMADO),
        ("aporte-3", "campanha-2", "investidor-A", 3000, StatusAporte.REJEITADO),
        ("aporte-4", "campanha-1", "investidor-B", 9000, StatusAporte.CONFIRMADO),
    ]

    for aporte_id, campanha_id, investidor_id, valor, status in registros:
        repositorio.salvar(
            Aporte(
                id=aporte_id,
                campanha_id=campanha_id,
                investidor_id=investidor_id,
                valor=Valor(valor),
                status=status,
            )
        )

    return TestClient(app), tmp_path


def test_investidor_visualiza_apenas_seus_aportes(
    ambiente: tuple[TestClient, Path],
) -> None:
    cliente, _ = ambiente

    resposta = cliente.get(
        "/aportes/meus",
        headers=autenticar_investidor("investidor-A"),
    )

    assert resposta.status_code == 200

    dados = resposta.json()

    assert dados["total"] == 3
    assert len(dados["itens"]) == 3
    assert all(item["investidorId"] == "investidor-A" for item in dados["itens"])


def test_investidor_nao_visualiza_aportes_de_outro(
    ambiente: tuple[TestClient, Path],
) -> None:
    cliente, _ = ambiente

    resposta = cliente.get(
        "/aportes/meus",
        headers=autenticar_investidor("investidor-B"),
    )

    assert resposta.status_code == 200

    dados = resposta.json()

    assert dados["total"] == 1
    assert dados["itens"][0]["aporteId"] == "aporte-4"
    assert all(item["investidorId"] == "investidor-B" for item in dados["itens"])


def test_historico_sem_autenticacao(
    ambiente: tuple[TestClient, Path],
) -> None:
    cliente, _ = ambiente

    resposta = cliente.get("/aportes/meus")

    assert resposta.status_code == 401


def test_paginacao_historico(
    ambiente: tuple[TestClient, Path],
) -> None:
    cliente, _ = ambiente

    resposta = cliente.get(
        "/aportes/meus",
        params={"pagina": 2, "tamanho_pagina": 2},
        headers=autenticar_investidor("investidor-A"),
    )

    assert resposta.status_code == 200

    dados = resposta.json()

    assert dados["pagina"] == 2
    assert dados["tamanhoPagina"] == 2
    assert dados["total"] == 3
    assert dados["totalPaginas"] == 2
    assert len(dados["itens"]) == 1
    assert all(item["investidorId"] == "investidor-A" for item in dados["itens"])


def test_filtro_por_campanha(
    ambiente: tuple[TestClient, Path],
) -> None:
    cliente, _ = ambiente

    resposta = cliente.get(
        "/aportes/meus",
        params={"campanha_id": "campanha-1"},
        headers=autenticar_investidor("investidor-A"),
    )

    assert resposta.status_code == 200

    dados = resposta.json()

    assert dados["total"] == 2
    assert all(item["campanhaId"] == "campanha-1" for item in dados["itens"])
    assert all(item["investidorId"] == "investidor-A" for item in dados["itens"])


def test_resumo_campanha_considera_apenas_confirmados(
    ambiente: tuple[TestClient, Path],
) -> None:
    cliente, _ = ambiente

    resposta = cliente.get(
        "/aportes/campanha/campanha-1/resumo",
    )

    assert resposta.status_code == 200

    dados = resposta.json()

    assert dados["campanhaId"] == "campanha-1"
    assert dados["total"] == 12000
    assert dados["quantidade"] == 3


def test_resumo_campanha_sem_aportes(
    ambiente: tuple[TestClient, Path],
) -> None:
    cliente, _ = ambiente

    resposta = cliente.get(
        "/aportes/campanha/campanha-inexistente/resumo",
    )

    assert resposta.status_code == 200

    dados = resposta.json()

    assert dados["total"] == 0
    assert dados["quantidade"] == 0


# ---------------------------------------------------------
# Testes de segurança do histórico
# ---------------------------------------------------------


def test_cabecalho_falsificado_nao_altera_investidor(
    ambiente: tuple[TestClient, Path],
) -> None:
    """Um X-User-ID falsificado não substitui o usuário do JWT."""
    cliente, _ = ambiente

    headers = autenticar_investidor("investidor-A")
    headers["X-User-ID"] = "investidor-B"

    resposta = cliente.get(
        "/aportes/meus",
        headers=headers,
    )

    assert resposta.status_code == 200

    dados = resposta.json()

    assert dados["total"] == 3
    assert all(item["investidorId"] == "investidor-A" for item in dados["itens"])


def test_historico_rejeita_token_invalido(
    ambiente: tuple[TestClient, Path],
) -> None:
    """Rejeita requisições com JWT inválido."""
    cliente, _ = ambiente

    resposta = cliente.get(
        "/aportes/meus",
        headers={"Authorization": "Bearer token-invalido"},
    )

    assert resposta.status_code == 401


def test_historico_rejeita_usuario_nao_investidor(
    ambiente: tuple[TestClient, Path],
) -> None:
    """Somente usuários com perfil INVESTIDOR acessam o histórico."""
    cliente, _ = ambiente
    segredo, _ = segredo_do_ambiente()

    token = emitir_token(
        sub="empreendedor-1",
        perfil="EMPREENDEDOR",
        segredo=segredo,
    )

    resposta = cliente.get(
        "/aportes/meus",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 403


def test_historico_rejeita_cabecalho_sem_jwt(
    ambiente: tuple[TestClient, Path],
) -> None:
    """Não confia em X-User-ID quando não existe JWT."""
    cliente, _ = ambiente

    resposta = cliente.get(
        "/aportes/meus",
        headers={"X-User-ID": "investidor-A"},
    )

    assert resposta.status_code == 401


def test_historico_rejeita_token_expirado(
    ambiente: tuple[TestClient, Path],
) -> None:
    """Rejeita tokens com prazo de validade expirado."""
    cliente, _ = ambiente
    segredo, _ = segredo_do_ambiente()

    token = emitir_token(
        sub="investidor-A",
        perfil="INVESTIDOR",
        segredo=segredo,
        expira_em_segundos=-60,
    )

    resposta = cliente.get(
        "/aportes/meus",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 401
