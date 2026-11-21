"""Testes HTTP de integração dos eventos da Custódia."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import custodia_retornos.app as modulo_app
from contracts.topicos import APORTE_CONFIRMADO, CAMPANHA_PUBLICADA
from shared.consumer import create_events_router


def criar_entrega(
    event_id: str,
    topic: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Cria uma entrega no formato esperado pelo broker."""
    return {
        "eventId": event_id,
        "topic": topic,
        "payload": {
            "eventId": event_id,
            "tipo": topic,
            "versão": 1,
            "ocorridoEm": datetime.now(UTC).isoformat(),
            "correlationId": "teste-custodia",
            "payload": payload,
        },
    }


def campanha_payload() -> dict[str, Any]:
    return {
        "campanhaId": "campanha-1",
        "empreendedorId": "empreendedor-1",
        "meta": 100000,
        "prazoFim": "2026-12-31T23:59:59Z",
    }


def aporte_payload() -> dict[str, Any]:
    return {
        "aporteId": "aporte-1",
        "campanhaId": "campanha-1",
        "investidorId": "investidor-1",
        "valor": 5000,
        "confirmadoEm": datetime.now(UTC).isoformat(),
    }


def criar_cliente(
    monkeypatch: Any,
    tmp_path: Path,
) -> TestClient:
    """Cria aplicação com rota de eventos sem iniciar broker real."""

    def configurar_messaging(
        app: Any,
        *,
        service: str,
        handlers: dict[str, Any],
        data_dir: str | Path,
        **kwargs: Any,
    ) -> None:
        app.include_router(
            create_events_router(
                service=service,
                handlers=handlers,
                data_dir=data_dir,
            )
        )

    monkeypatch.setattr(
        modulo_app,
        "configure_messaging",
        configurar_messaging,
    )

    app = modulo_app.criar_custodia_app(tmp_path)
    return TestClient(app)


def test_aplicacao_inicializa_migrations(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    with criar_cliente(monkeypatch, tmp_path):
        from shared.db import open_db

        with open_db("custodia_retornos", tmp_path) as conn:
            tabelas = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }

    assert "custodia_contas" in tabelas
    assert "custodia_movimentacoes" in tabelas


def test_eventos_abrem_conta_e_registram_retencao(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    from shared.db import open_db

    with criar_cliente(monkeypatch, tmp_path) as client:
        campanha = client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-1",
                CAMPANHA_PUBLICADA,
                campanha_payload(),
            ),
        )

        aporte = client.post(
            "/events",
            json=criar_entrega(
                "evento-aporte-1",
                APORTE_CONFIRMADO,
                aporte_payload(),
            ),
        )

    assert campanha.status_code == 200
    assert campanha.json()["processed"] is True

    assert aporte.status_code == 200
    assert aporte.json()["processed"] is True

    with open_db("custodia_retornos", tmp_path) as conn:
        conta = conn.execute(
            "SELECT saldo_retido FROM custodia_contas WHERE campanha_id = ?",
            ("campanha-1",),
        ).fetchone()

        assert conta is not None
        assert conta[0] == 5000


def test_dez_entregas_do_mesmo_aporte_geram_uma_retencao(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    from shared.db import open_db

    with criar_cliente(monkeypatch, tmp_path) as client:
        client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-1",
                CAMPANHA_PUBLICADA,
                campanha_payload(),
            ),
        )

        respostas = [
            client.post(
                "/events",
                json=criar_entrega(
                    f"evento-aporte-{i}",
                    APORTE_CONFIRMADO,
                    aporte_payload(),
                ),
            )
            for i in range(10)
        ]

    assert all(resposta.status_code == 200 for resposta in respostas)

    with open_db("custodia_retornos", tmp_path) as conn:
        quantidade = conn.execute(
            """
            SELECT COUNT(*)
            FROM custodia_movimentacoes
            WHERE aporte_id = ? AND tipo = 'RETENCAO'
            """,
            ("aporte-1",),
        ).fetchone()

        saldo = conn.execute(
            "SELECT saldo_retido FROM custodia_contas WHERE campanha_id = ?",
            ("campanha-1",),
        ).fetchone()

    assert quantidade is not None
    assert quantidade[0] == 1
    assert saldo is not None
    assert saldo[0] == 5000


def test_aporte_antes_da_campanha_pode_ser_reprocessado(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    with criar_cliente(monkeypatch, tmp_path) as client:
        entrega = criar_entrega(
            "evento-aporte-antecipado",
            APORTE_CONFIRMADO,
            aporte_payload(),
        )

        primeira = client.post("/events", json=entrega)

        assert primeira.status_code == 500

        campanha = client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-1",
                CAMPANHA_PUBLICADA,
                campanha_payload(),
            ),
        )

        segunda = client.post("/events", json=entrega)

    assert campanha.status_code == 200
    assert segunda.status_code == 200
    assert segunda.json()["processed"] is True


def test_resultado_sucesso_liquida_campanha_via_http(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """Processa resultado via HTTP e liquida a campanha uma única vez."""
    from contracts.topicos import RESULTADO_CAMPANHA
    from shared.db import open_db

    monkeypatch.setenv("CUSTODIA_TAXA_PERCENTUAL", "10")

    resultado_payload = {
        "campanhaId": "campanha-1",
        "empreendedorId": "empreendedor-1",
        "resultado": "SUCESSO",
        "valorArrecadado": 100000,
        "investidorIds": ["investidor-1"],
        "encerradaEm": "2026-11-20T00:00:00Z",
    }

    with criar_cliente(monkeypatch, tmp_path) as client:
        campanha = client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-liquidacao",
                CAMPANHA_PUBLICADA,
                campanha_payload(),
            ),
        )
        assert campanha.status_code == 200

        aporte = client.post(
            "/events",
            json=criar_entrega(
                "evento-aporte-liquidacao",
                APORTE_CONFIRMADO,
                {
                    "aporteId": "aporte-liquidacao",
                    "campanhaId": "campanha-1",
                    "investidorId": "investidor-1",
                    "valor": 100000,
                    "confirmadoEm": "2026-11-20T00:00:00Z",
                },
            ),
        )
        assert aporte.status_code == 200

        # Simula o resultado persistido pela apuração da Issue #26.
        with open_db("custodia_retornos", tmp_path) as conn:
            conn.execute(
                """
                INSERT INTO custodia_resultados (
                    campanha_id, resultado, valor_arrecadado, encerrada_em
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    "campanha-1",
                    "SUCESSO",
                    100000,
                    "2026-11-20T00:00:00+00:00",
                ),
            )

        entrega = criar_entrega(
            "evento-resultado-liquidacao",
            RESULTADO_CAMPANHA,
            resultado_payload,
        )

        primeira = client.post("/events", json=entrega)
        segunda = client.post("/events", json=entrega)

    assert primeira.status_code == 200
    assert primeira.json()["processed"] is True
    assert segunda.status_code == 200
    assert segunda.json()["processed"] is False

    with open_db("custodia_retornos", tmp_path) as conn:
        saldo = conn.execute(
            """
            SELECT saldo_retido
            FROM custodia_contas
            WHERE campanha_id = ?
            """,
            ("campanha-1",),
        ).fetchone()

        movimentacoes = conn.execute(
            """
            SELECT tipo, valor
            FROM custodia_movimentacoes
            WHERE campanha_id = ?
            """,
            ("campanha-1",),
        ).fetchall()

        liquidacoes = conn.execute(
            """
            SELECT COUNT(*)
            FROM custodia_liquidacoes
            WHERE campanha_id = ?
            """,
            ("campanha-1",),
        ).fetchone()

    assert saldo is not None and saldo[0] == 0
    assert sorted(movimentacoes) == [
        ("LIBERACAO", 90000),
        ("RETENCAO", 100000),
        ("TAXA", 10000),
    ]
    assert liquidacoes is not None and liquidacoes[0] == 1


def test_resultado_falha_devolve_aportes_via_http(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """Devolve integralmente os aportes quando a campanha falha."""
    from contracts.topicos import RESULTADO_CAMPANHA
    from shared.db import open_db

    monkeypatch.setenv("CUSTODIA_TAXA_PERCENTUAL", "10")

    encerrada = "2026-11-20T00:00:00Z"

    resultado_payload = {
        "campanhaId": "campanha-1",
        "empreendedorId": "empreendedor-1",
        "resultado": "FALHA",
        "valorArrecadado": 90000,
        "investidorIds": ["investidor-1", "investidor-2"],
        "encerradaEm": encerrada,
    }

    with criar_cliente(monkeypatch, tmp_path) as client:
        client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-falha",
                CAMPANHA_PUBLICADA,
                campanha_payload(),
            ),
        )

        for indice, investidor, valor in (
            (1, "investidor-1", 60000),
            (2, "investidor-2", 30000),
        ):
            resposta = client.post(
                "/events",
                json=criar_entrega(
                    f"evento-aporte-falha-{indice}",
                    APORTE_CONFIRMADO,
                    {
                        "aporteId": f"aporte-falha-{indice}",
                        "campanhaId": "campanha-1",
                        "investidorId": investidor,
                        "valor": valor,
                        "confirmadoEm": encerrada,
                    },
                ),
            )
            assert resposta.status_code == 200

        with open_db("custodia_retornos", tmp_path) as conn:
            conn.execute(
                """
                INSERT INTO custodia_resultados (
                    campanha_id, resultado, valor_arrecadado, encerrada_em
                )
                VALUES (?, ?, ?, ?)
                """,
                ("campanha-1", "FALHA", 90000, encerrada),
            )

        resposta = client.post(
            "/events",
            json=criar_entrega(
                "evento-resultado-falha",
                RESULTADO_CAMPANHA,
                resultado_payload,
            ),
        )

    assert resposta.status_code == 200
    assert resposta.json()["processed"] is True

    with open_db("custodia_retornos", tmp_path) as conn:
        saldo = conn.execute(
            """
            SELECT saldo_retido
            FROM custodia_contas
            WHERE campanha_id = ?
            """,
            ("campanha-1",),
        ).fetchone()

        devolucoes = conn.execute(
            """
            SELECT aporte_id, valor
            FROM custodia_movimentacoes
            WHERE campanha_id = ? AND tipo = 'DEVOLUCAO'
            ORDER BY aporte_id
            """,
            ("campanha-1",),
        ).fetchall()

        liquidacoes = conn.execute(
            """
            SELECT COUNT(*)
            FROM custodia_liquidacoes
            WHERE campanha_id = ?
            """,
            ("campanha-1",),
        ).fetchone()

        eventos = conn.execute(
            """
            SELECT COUNT(*)
            FROM outbox_evento
            WHERE tipo_evento = 'campanha.liquidada'
            """,
        ).fetchone()

    assert saldo is not None and saldo[0] == 0
    assert devolucoes == [
        ("aporte-falha-1", 60000),
        ("aporte-falha-2", 30000),
    ]
    assert liquidacoes is not None and liquidacoes[0] == 1
    assert eventos is not None and eventos[0] == 0


def criar_token_investidor(investidor_id: str, perfil: str = "INVESTIDOR") -> str:
    """Gera JWT válido para os testes de participações."""
    from shared.auth import emitir_token, segredo_do_ambiente

    segredo, _ = segredo_do_ambiente()

    return emitir_token(
        sub=investidor_id,
        perfil=perfil,
        segredo=segredo,
    )


def test_minhas_participacoes_retorna_apenas_do_investidor(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """Cada investidor consulta somente suas próprias participações."""
    from contracts.topicos import CAMPANHA_LIQUIDADA

    with criar_cliente(monkeypatch, tmp_path) as client:
        campanha = client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-participacoes",
                CAMPANHA_PUBLICADA,
                campanha_payload(),
            ),
        )
        assert campanha.status_code == 200

        aportes = [
            ("aporte-a", "investidor-A", 6000),
            ("aporte-b", "investidor-B", 4000),
        ]

        for aporte_id, investidor_id, valor in aportes:
            resposta = client.post(
                "/events",
                json=criar_entrega(
                    f"evento-{aporte_id}",
                    APORTE_CONFIRMADO,
                    {
                        "aporteId": aporte_id,
                        "campanhaId": "campanha-1",
                        "investidorId": investidor_id,
                        "valor": valor,
                        "confirmadoEm": datetime.now(UTC).isoformat(),
                    },
                ),
            )
            assert resposta.status_code == 200

        liquidacao = client.post(
            "/events",
            json=criar_entrega(
                "evento-liquidacao-participacoes",
                CAMPANHA_LIQUIDADA,
                {
                    "campanhaId": "campanha-1",
                    "valorBruto": 10000,
                    "taxaPlataforma": 0,
                    "valorLiquido": 10000,
                    "liquidadaEm": datetime.now(UTC).isoformat(),
                    "aportes": ["aporte-a", "aporte-b"],
                },
            ),
        )
        assert liquidacao.status_code == 200

        token_a = criar_token_investidor("investidor-A")
        token_b = criar_token_investidor("investidor-B")

        resposta_a = client.get(
            "/retornos/minhas-participacoes",
            headers={"Authorization": f"Bearer {token_a}"},
        )

        resposta_b = client.get(
            "/retornos/minhas-participacoes",
            headers={"Authorization": f"Bearer {token_b}"},
        )

    assert resposta_a.status_code == 200
    assert resposta_b.status_code == 200

    dados_a = resposta_a.json()
    dados_b = resposta_b.json()

    assert len(dados_a) == 1
    assert len(dados_b) == 1

    assert dados_a[0]["valorAportado"] == 6000
    assert dados_a[0]["percentual"] == "0.6000"

    assert dados_b[0]["valorAportado"] == 4000
    assert dados_b[0]["percentual"] == "0.4000"


def test_minhas_participacoes_sem_token_retorna_401(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    with criar_cliente(monkeypatch, tmp_path) as client:
        resposta = client.get("/retornos/minhas-participacoes")

    assert resposta.status_code == 401


def test_minhas_participacoes_com_token_invalido_retorna_401(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    with criar_cliente(monkeypatch, tmp_path) as client:
        resposta = client.get(
            "/retornos/minhas-participacoes",
            headers={"Authorization": "Bearer token-invalido"},
        )

    assert resposta.status_code == 401


def test_minhas_participacoes_usuario_nao_investidor_retorna_403(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    token = criar_token_investidor(
        "empreendedor-1",
        perfil="EMPREENDEDOR",
    )

    with criar_cliente(monkeypatch, tmp_path) as client:
        resposta = client.get(
            "/retornos/minhas-participacoes",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resposta.status_code == 403


def test_distribuicao_proporcional_via_http(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """Distribui retornos proporcionalmente e disponibiliza o extrato."""
    from contracts.topicos import CAMPANHA_LIQUIDADA, RESULTADO_CAMPANHA
    from shared.db import open_db

    with criar_cliente(monkeypatch, tmp_path) as client:
        # Publicar campanha.
        resposta = client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-distribuicao",
                CAMPANHA_PUBLICADA,
                campanha_payload(),
            ),
        )
        assert resposta.status_code == 200

        # Registrar aportes dos dois investidores.
        for aporte_id, investidor_id, valor in [
            ("aporte-dist-a", "investidor-A", 6000),
            ("aporte-dist-b", "investidor-B", 4000),
        ]:
            resposta = client.post(
                "/events",
                json=criar_entrega(
                    f"evento-{aporte_id}",
                    APORTE_CONFIRMADO,
                    {
                        "aporteId": aporte_id,
                        "campanhaId": "campanha-1",
                        "investidorId": investidor_id,
                        "valor": valor,
                        "confirmadoEm": datetime.now(UTC).isoformat(),
                    },
                ),
            )
            assert resposta.status_code == 200

        # Simula o resultado persistido pela apuração da Issue #26.
        with open_db("custodia_retornos", tmp_path) as conn:
            conn.execute(
                """
                INSERT INTO custodia_resultados (
                    campanha_id, resultado, valor_arrecadado, encerrada_em
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    "campanha-1",
                    "SUCESSO",
                    10000,
                    datetime.now(UTC).isoformat(),
                ),
            )

        # Registrar resultado de sucesso.
        resposta = client.post(
            "/events",
            json=criar_entrega(
                "evento-resultado-distribuicao",
                RESULTADO_CAMPANHA,
                {
                    "campanhaId": "campanha-1",
                    "empreendedorId": "empreendedor-1",
                    "resultado": "SUCESSO",
                    "valorArrecadado": 10000,
                    "investidorIds": ["investidor-A", "investidor-B"],
                    "encerradaEm": datetime.now(UTC).isoformat(),
                },
            ),
        )
        assert resposta.status_code == 200

        # Criar participações a partir da liquidação.
        resposta = client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-liquidada-distribuicao",
                CAMPANHA_LIQUIDADA,
                {
                    "campanhaId": "campanha-1",
                    "valorBruto": 10000,
                    "taxaPlataforma": 0,
                    "valorLiquido": 10000,
                    "liquidadaEm": datetime.now(UTC).isoformat(),
                    "aportes": ["aporte-dist-a", "aporte-dist-b"],
                },
            ),
        )
        assert resposta.status_code == 200

        token_empreendedor = criar_token_investidor(
            "empreendedor-1",
            perfil="EMPREENDEDOR",
        )

        # Distribuir 10.000 centavos.
        resposta = client.post(
            "/retornos/campanhas/campanha-1/distribuir",
            headers={"Authorization": f"Bearer {token_empreendedor}"},
            json={"valorTotal": 10000},
        )

        assert resposta.status_code == 200
        assert resposta.json()["valorTotal"] == 10000

        distribuicoes = resposta.json()["distribuicoes"]

        assert sum(item["valor"] for item in distribuicoes) == 10000

        valores = {item["investidorId"]: item["valor"] for item in distribuicoes}

        assert valores == {
            "investidor-A": 6000,
            "investidor-B": 4000,
        }

        # Consultar extrato individual.
        token_a = criar_token_investidor("investidor-A")
        token_b = criar_token_investidor("investidor-B")

        extrato_a = client.get(
            "/retornos/extrato",
            headers={"Authorization": f"Bearer {token_a}"},
        )

        extrato_b = client.get(
            "/retornos/extrato",
            headers={"Authorization": f"Bearer {token_b}"},
        )

        assert extrato_a.status_code == 200
        assert extrato_b.status_code == 200

        assert sum(item["valor"] for item in extrato_a.json()) == 6000
        assert sum(item["valor"] for item in extrato_b.json()) == 4000

        # Conferir eventos registrados na outbox.
        with open_db("custodia_retornos", tmp_path) as conn:
            eventos = conn.execute(
                """
                SELECT COUNT(*)
                FROM outbox_evento
                WHERE tipo_evento = 'retorno.distribuido'
                """,
            ).fetchone()

            assert eventos is not None
            assert eventos[0] == 2

            # Lotes e itens financeiros devem ser append-only.
            lote = conn.execute(
                """
                SELECT lote_id
                FROM retornos_lotes_distribuicao
                WHERE campanha_id = ?
                """,
                ("campanha-1",),
            ).fetchone()

            item = conn.execute(
                """
                SELECT retorno_id
                FROM retornos_distribuicao_itens
                WHERE campanha_id = ?
                LIMIT 1
                """,
                ("campanha-1",),
            ).fetchone()

            assert lote is not None
            assert item is not None

            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE retornos_lotes_distribuicao "
                    "SET valor_total = valor_total + 1 WHERE lote_id = ?",
                    (lote[0],),
                )

            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "DELETE FROM retornos_lotes_distribuicao WHERE lote_id = ?",
                    (lote[0],),
                )

            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE retornos_distribuicao_itens SET valor = valor + 1 WHERE retorno_id = ?",
                    (item[0],),
                )

            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "DELETE FROM retornos_distribuicao_itens WHERE retorno_id = ?",
                    (item[0],),
                )


def test_rejeita_distribuicao_de_campanha_nao_liquidada(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """Não permite distribuir retornos antes da liquidação."""
    with criar_cliente(monkeypatch, tmp_path) as client:
        campanha = client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-nao-liquidada",
                CAMPANHA_PUBLICADA,
                campanha_payload(),
            ),
        )
        assert campanha.status_code == 200

        token = criar_token_investidor(
            "empreendedor-1",
            perfil="EMPREENDEDOR",
        )

        resposta = client.post(
            "/retornos/campanhas/campanha-1/distribuir",
            headers={"Authorization": f"Bearer {token}"},
            json={"valorTotal": 10000},
        )

    assert resposta.status_code in (400, 409)


def test_outro_empreendedor_nao_pode_distribuir(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """Impede que outro empreendedor distribua retornos da campanha."""
    with criar_cliente(monkeypatch, tmp_path) as client:
        client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-outro-empreendedor",
                CAMPANHA_PUBLICADA,
                campanha_payload(),
            ),
        )

        token = criar_token_investidor(
            "empreendedor-2",
            perfil="EMPREENDEDOR",
        )

        resposta = client.post(
            "/retornos/campanhas/campanha-1/distribuir",
            headers={"Authorization": f"Bearer {token}"},
            json={"valorTotal": 10000},
        )

    assert resposta.status_code == 403


def test_investidor_nao_pode_distribuir(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """Impede que investidores executem distribuições."""
    with criar_cliente(monkeypatch, tmp_path) as client:
        client.post(
            "/events",
            json=criar_entrega(
                "evento-campanha-investidor",
                CAMPANHA_PUBLICADA,
                campanha_payload(),
            ),
        )

        token = criar_token_investidor("investidor-A")

        resposta = client.post(
            "/retornos/campanhas/campanha-1/distribuir",
            headers={"Authorization": f"Bearer {token}"},
            json={"valorTotal": 10000},
        )

    assert resposta.status_code == 403


def test_distribuicao_sem_token_retorna_401(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """Exige autenticação para distribuir retornos."""
    with criar_cliente(monkeypatch, tmp_path) as client:
        resposta = client.post(
            "/retornos/campanhas/campanha-1/distribuir",
            json={"valorTotal": 10000},
        )

    assert resposta.status_code == 401


@pytest.mark.parametrize(
    "topic",
    [
        "campanha.publicada",
        "aporte.confirmado",
        "campanha.resultado",
        "campanha.liquidada",
    ],
)
def test_consumidores_rejeitam_payloads_invalidos_via_http(
    topic: str,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """Os consumidores reais rejeitam payloads inválidos pelo endpoint HTTP."""
    with criar_cliente(monkeypatch, tmp_path) as client:
        resposta = client.post(
            "/events",
            json=criar_entrega(
                f"evento-invalido-{topic}",
                topic,
                {},
            ),
        )

    assert resposta.status_code == 422
    assert resposta.json()
