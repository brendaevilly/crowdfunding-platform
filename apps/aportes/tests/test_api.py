"""Testes HTTP do endpoint POST /aportes."""

import sqlite3
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from aportes.api import criar_router
from aportes.cliente_campanhas import (
    CampanhaIndisponivelError,
    ClienteCampanhas,
)
from aportes.repository import inicializar_banco
from shared.db import transaction


class ClienteCampanhasFalso:
    """Simula as respostas do serviço de Campanhas."""

    def __init__(
        self,
        *,
        aceita: bool = True,
        indisponivel: bool = False,
    ) -> None:
        self.aceita = aceita
        self.indisponivel = indisponivel
        self.consultas = 0

    async def aceita_aportes(self, campanha_id: str) -> bool:
        self.consultas += 1

        if self.indisponivel:
            raise CampanhaIndisponivelError("Serviço de Campanhas indisponível.")

        return self.aceita


@pytest.fixture
def ambiente(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, ClienteCampanhasFalso, Path]:
    """Prepara a API e um banco isolado para cada teste."""

    monkeypatch.setenv("LIMITE_APORTE_CENTAVOS", "100000")

    inicializar_banco(tmp_path)

    cliente_falso = ClienteCampanhasFalso()

    app = FastAPI()
    app.include_router(
        criar_router(
            cliente_campanhas=cast(
                ClienteCampanhas,
                cliente_falso,
            ),
            data_dir=tmp_path,
        )
    )

    return TestClient(app), cliente_falso, tmp_path


def enviar_aporte(
    cliente: TestClient,
    *,
    chave: str = "chave-1",
    valor: int = 5000,
    campanha_id: str = "campanha-1",
    investidor_id: str = "investidor-1",
) -> Response:
    """Envia uma requisição HTTP de aporte."""

    resposta = cliente.post(
        "/aportes",
        headers={"Idempotency-Key": chave},
        json={
            "campanhaId": campanha_id,
            "investidorId": investidor_id,
            "valor": valor,
        },
    )

    return cast(Response, resposta)


def contar_registros(data_dir: Path) -> tuple[int, int, int]:
    """Conta aportes, eventos na outbox e chaves registradas."""

    def consultar(conn: sqlite3.Connection) -> tuple[int, int, int]:
        aportes = conn.execute("SELECT COUNT(*) FROM aporte").fetchone()[0]

        eventos = conn.execute("SELECT COUNT(*) FROM outbox_evento").fetchone()[0]

        requisicoes = conn.execute("SELECT COUNT(*) FROM aporte_requisicao").fetchone()[0]

        return int(aportes), int(eventos), int(requisicoes)

    return transaction(consultar, "aportes", data_dir)


def test_campanha_publicada_confirma_aporte(
    ambiente: tuple[TestClient, ClienteCampanhasFalso, Path],
) -> None:
    cliente, campanhas, banco = ambiente

    resposta = enviar_aporte(cliente)

    assert resposta.status_code == 201
    assert resposta.json()["status"] == "CONFIRMADO"
    assert resposta.json()["valor"] == 5000
    assert campanhas.consultas == 1
    assert contar_registros(banco) == (1, 2, 1)


def test_mesma_chave_retorna_mesma_resposta(
    ambiente: tuple[TestClient, ClienteCampanhasFalso, Path],
) -> None:
    cliente, campanhas, banco = ambiente

    primeira = enviar_aporte(cliente)

    campanhas.indisponivel = True

    segunda = enviar_aporte(cliente)

    assert primeira.status_code == 201
    assert segunda.status_code == 201
    assert primeira.json() == segunda.json()
    assert campanhas.consultas == 1
    assert contar_registros(banco) == (1, 2, 1)


def test_mesma_chave_com_dados_diferentes_rejeita(
    ambiente: tuple[TestClient, ClienteCampanhasFalso, Path],
) -> None:
    cliente, campanhas, banco = ambiente

    primeira = enviar_aporte(cliente, valor=5000)
    segunda = enviar_aporte(cliente, valor=9000)

    assert primeira.status_code == 201
    assert segunda.status_code == 409
    assert campanhas.consultas == 1
    assert contar_registros(banco) == (1, 2, 1)


def test_campanha_encerrada_rejeita_aporte(
    ambiente: tuple[TestClient, ClienteCampanhasFalso, Path],
) -> None:
    cliente, campanhas, banco = ambiente
    campanhas.aceita = False

    resposta = enviar_aporte(cliente)

    assert resposta.status_code == 409
    assert campanhas.consultas == 1
    assert contar_registros(banco) == (0, 0, 0)


def test_campanhas_indisponivel_nao_confirma(
    ambiente: tuple[TestClient, ClienteCampanhasFalso, Path],
) -> None:
    """Indisponibilidade rejeita o aporte sem gerar eventos."""

    cliente, campanhas, banco = ambiente
    campanhas.indisponivel = True

    resposta = enviar_aporte(cliente)

    assert resposta.status_code == 503
    assert resposta.json()["status"] == "REJEITADO"
    assert campanhas.consultas == 1
    assert contar_registros(banco) == (1, 0, 1)


def test_investidor_bloqueado_nao_pode_aportar(
    ambiente: tuple[TestClient, ClienteCampanhasFalso, Path],
) -> None:
    cliente, campanhas, banco = ambiente

    def bloquear(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO investidor_status (
                investidor_id, status, alterado_em
            )
            VALUES (?, ?, ?)
            """,
            (
                "investidor-1",
                "BLOQUEADO",
                "2026-11-19T12:00:00+00:00",
            ),
        )

    transaction(bloquear, "aportes", banco)

    resposta = enviar_aporte(cliente)

    assert resposta.status_code == 403
    assert campanhas.consultas == 0
    assert contar_registros(banco) == (0, 0, 0)


def test_aporte_acima_do_limite_sem_kyc_rejeitado(
    ambiente: tuple[TestClient, ClienteCampanhasFalso, Path],
) -> None:
    cliente, campanhas, banco = ambiente

    resposta = enviar_aporte(cliente, valor=150000)

    assert resposta.status_code == 422
    assert campanhas.consultas == 0
    assert contar_registros(banco) == (0, 0, 0)


def test_aporte_acima_do_limite_com_kyc_permitido(
    ambiente: tuple[TestClient, ClienteCampanhasFalso, Path],
) -> None:
    cliente, campanhas, banco = ambiente

    def verificar(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO investidor_verificado (investidor_id)
            VALUES (?)
            """,
            ("investidor-1",),
        )

    transaction(verificar, "aportes", banco)

    resposta = enviar_aporte(cliente, valor=150000)

    assert resposta.status_code == 201
    assert campanhas.consultas == 1
    assert contar_registros(banco) == (1, 2, 1)


def test_idempotency_key_obrigatoria(
    ambiente: tuple[TestClient, ClienteCampanhasFalso, Path],
) -> None:
    cliente, campanhas, banco = ambiente

    resposta = cliente.post(
        "/aportes",
        json={
            "campanhaId": "campanha-1",
            "investidorId": "investidor-1",
            "valor": 5000,
        },
    )

    assert resposta.status_code == 422
    assert campanhas.consultas == 0
    assert contar_registros(banco) == (0, 0, 0)


def test_valor_zero_rejeitado(
    ambiente: tuple[TestClient, ClienteCampanhasFalso, Path],
) -> None:
    cliente, campanhas, banco = ambiente

    resposta = enviar_aporte(cliente, valor=0)

    assert resposta.status_code == 422
    assert campanhas.consultas == 0
    assert contar_registros(banco) == (0, 0, 0)


def test_aporte_confirmado_apos_recuperacao_de_campanhas(
    ambiente: tuple[TestClient, ClienteCampanhasFalso, Path],
) -> None:
    """Uma nova chave permite aportar após a recuperação."""

    cliente, campanhas, banco = ambiente

    # Campanhas está indisponível.
    campanhas.indisponivel = True

    primeira = enviar_aporte(
        cliente,
        chave="chave-recuperacao-campanhas",
    )

    assert primeira.status_code == 503
    assert primeira.json()["status"] == "REJEITADO"
    assert campanhas.consultas == 1
    assert contar_registros(banco) == (1, 0, 1)

    # Campanhas volta a funcionar.
    campanhas.indisponivel = False

    # Uma nova chave representa uma nova tentativa.
    segunda = enviar_aporte(
        cliente,
        chave="chave-recuperacao-campanhas-nova",
    )

    assert segunda.status_code == 201
    assert segunda.json()["status"] == "CONFIRMADO"
    assert campanhas.consultas == 2
    assert contar_registros(banco) == (2, 2, 2)

    # Repetir a chave da confirmação não duplica o aporte.
    terceira = enviar_aporte(
        cliente,
        chave="chave-recuperacao-campanhas-nova",
    )

    assert terceira.status_code == 201
    assert terceira.json() == segunda.json()
    assert campanhas.consultas == 2
    assert contar_registros(banco) == (2, 2, 2)


def test_rejeicao_por_indisponibilidade_e_idempotente(
    ambiente: tuple[TestClient, ClienteCampanhasFalso, Path],
) -> None:
    """A mesma chave mantém a rejeição após a recuperação."""

    cliente, campanhas, banco = ambiente
    campanhas.indisponivel = True

    primeira = enviar_aporte(
        cliente,
        chave="chave-rejeitada",
    )

    campanhas.indisponivel = False

    segunda = enviar_aporte(
        cliente,
        chave="chave-rejeitada",
    )

    assert primeira.status_code == 503
    assert segunda.status_code == 503
    assert primeira.json() == segunda.json()
    assert primeira.json()["status"] == "REJEITADO"
    assert campanhas.consultas == 1
    assert contar_registros(banco) == (1, 0, 1)


def test_rejeicao_nao_cria_pendencia_custodia(
    ambiente: tuple[TestClient, ClienteCampanhasFalso, Path],
) -> None:
    """Aporte rejeitado não gera pendência de Custódia."""

    cliente, campanhas, banco = ambiente
    campanhas.indisponivel = True

    resposta = enviar_aporte(
        cliente,
        chave="chave-sem-custodia",
    )

    def contar_pendencias(conn: sqlite3.Connection) -> int:
        return int(conn.execute("SELECT COUNT(*) FROM aporte_custodia").fetchone()[0])

    pendencias = transaction(
        contar_pendencias,
        "aportes",
        banco,
    )

    assert resposta.status_code == 503
    assert resposta.json()["status"] == "REJEITADO"
    assert contar_registros(banco) == (1, 0, 1)
    assert pendencias == 0
