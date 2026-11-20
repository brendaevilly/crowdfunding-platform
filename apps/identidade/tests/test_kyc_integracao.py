"""Testes de integração, idempotência e proteção do KYC."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts.eventos import Perfil, UsuarioCadastrado
from contracts.topicos import USUARIO_CADASTRADO
from identidade.contas.servico import cadastrar_usuario
from identidade.kyc.consumidor import consumir_usuario_cadastrado
from identidade.kyc.servico import processar_usuario_cadastrado
from shared.consumer import create_events_router
from shared.db import migrate, transaction
from shared.messaging_schema import install_messaging_schema

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


@pytest.fixture
def ambiente(tmp_path: Path) -> Path:
    migrate("identidade", MIGRATIONS_DIR, tmp_path)
    install_messaging_schema("identidade", tmp_path)
    return tmp_path


def criar_usuario(data_dir: Path) -> str:
    usuario = cadastrar_usuario(
        nome="Usuário Integração KYC",
        email_str=f"integracao-{uuid4()}@exemplo.com",
        senha_plana="SenhaSegura123!",
        perfil=Perfil.INVESTIDOR,
        data_dir=data_dir,
    )
    return usuario.id


def contar_verificacoes(data_dir: Path, usuario_id: str) -> int:
    def contar(conn: sqlite3.Connection) -> int:
        linha = conn.execute(
            """
            SELECT COUNT(*)
            FROM kyc_verificacoes
            WHERE usuario_id = ?
            """,
            (usuario_id,),
        ).fetchone()
        assert linha is not None
        return int(linha[0])

    return transaction(contar, "identidade", data_dir)


def criar_entrega(usuario_id: str, event_id: str) -> dict[str, object]:
    payload = UsuarioCadastrado(
        usuario_id=usuario_id,
        perfil=Perfil.INVESTIDOR,
        cadastrado_em=datetime.now(UTC),
    ).model_dump(by_alias=True, mode="json")

    return {
        "eventId": event_id,
        "topic": USUARIO_CADASTRADO,
        "payload": {
            "eventId": event_id,
            "tipo": USUARIO_CADASTRADO,
            "versão": 1,
            "ocorridoEm": datetime.now(UTC).isoformat(),
            "correlationId": str(uuid4()),
            "payload": payload,
        },
    }


def test_eventos_diferentes_mesmo_usuario_nao_duplicam_kyc(
    ambiente: Path,
) -> None:
    usuario_id = criar_usuario(ambiente)

    app = FastAPI()
    app.include_router(
        create_events_router(
            service="identidade",
            handlers={
                USUARIO_CADASTRADO: consumir_usuario_cadastrado,
            },
            data_dir=ambiente,
        )
    )

    primeira_entrega = criar_entrega(usuario_id, str(uuid4()))
    segunda_entrega = criar_entrega(usuario_id, str(uuid4()))

    with TestClient(app) as cliente:
        primeira = cliente.post("/events", json=primeira_entrega)
        segunda = cliente.post("/events", json=segunda_entrega)

    assert primeira.status_code == 200
    assert segunda.status_code == 200

    # Ambos os eventos são inéditos para o consumidor.
    assert primeira.json()["processed"] is True
    assert segunda.json()["processed"] is True

    # Mas o KYC é inicializado uma única vez por usuarioId.
    assert contar_verificacoes(ambiente, usuario_id) == 1


def test_aprovada_nao_pode_ser_alterada_ou_excluida(
    ambiente: Path,
) -> None:
    usuario_id = criar_usuario(ambiente)

    transaction(
        lambda conn: processar_usuario_cadastrado(conn, usuario_id),
        "identidade",
        ambiente,
    )

    def aprovar(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            UPDATE kyc_verificacoes
            SET status = 'APROVADA'
            WHERE usuario_id = ?
              AND status = 'PENDENTE'
            """,
            (usuario_id,),
        )

    transaction(aprovar, "identidade", ambiente)

    with pytest.raises(sqlite3.IntegrityError):
        transaction(
            lambda conn: conn.execute(
                """
                UPDATE kyc_verificacoes
                SET status = 'REPROVADA'
                WHERE usuario_id = ?
                """,
                (usuario_id,),
            ),
            "identidade",
            ambiente,
        )

    with pytest.raises(sqlite3.IntegrityError):
        transaction(
            lambda conn: conn.execute(
                """
                DELETE FROM kyc_verificacoes
                WHERE usuario_id = ?
                """,
                (usuario_id,),
            ),
            "identidade",
            ambiente,
        )

    def verificar(conn: sqlite3.Connection) -> str:
        linha = conn.execute(
            """
            SELECT status
            FROM kyc_verificacoes
            WHERE usuario_id = ?
            """,
            (usuario_id,),
        ).fetchone()
        assert linha is not None
        return str(linha[0])

    assert transaction(verificar, "identidade", ambiente) == "APROVADA"


def test_indice_unico_impede_duas_pendentes(
    ambiente: Path,
) -> None:
    usuario_id = criar_usuario(ambiente)

    transaction(
        lambda conn: processar_usuario_cadastrado(conn, usuario_id),
        "identidade",
        ambiente,
    )

    with pytest.raises(sqlite3.IntegrityError):
        transaction(
            lambda conn: conn.execute(
                """
                INSERT INTO kyc_verificacoes (
                    id, usuario_id, status
                )
                VALUES (?, ?, 'PENDENTE')
                """,
                (str(uuid4()), usuario_id),
            ),
            "identidade",
            ambiente,
        )

    assert contar_verificacoes(ambiente, usuario_id) == 1
