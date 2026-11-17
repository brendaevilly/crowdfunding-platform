"""Testes do relay da outbox transacional."""

import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from shared.db import transaction
from shared.messaging_schema import install_messaging_schema
from shared.outbox import OutboxEvent, add
from shared.relay import publish_pending


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Prepara o banco temporário."""
    install_messaging_schema("campanhas", tmp_path)
    return tmp_path


def criar_evento(data_dir: Path) -> str:
    """Registra um evento pendente na outbox."""

    def salvar(conn: sqlite3.Connection) -> str:
        return add(
            conn,
            OutboxEvent(
                agregado_id="campanha-1",
                tipo_evento="CampanhaPublicada",
                payload={"campanhaId": "campanha-1"},
                correlation_id="correlation-1",
            ),
        )

    return transaction(salvar, "campanhas", data_dir)


def consultar_status(data_dir: Path, event_id: str) -> tuple[Any, ...]:
    """Consulta o status de um evento."""

    def consultar(conn: sqlite3.Connection) -> tuple[Any, ...] | None:
        row: tuple[Any, ...] | None = conn.execute(
            """
            SELECT status, published_at
            FROM outbox_evento
            WHERE outbox_id = ?
            """,
            (event_id,),
        ).fetchone()
        return row

    res = transaction(consultar, "campanhas", data_dir)
    assert res is not None
    return res


def test_relay_publica_evento_com_sucesso(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Após confirmação do broker, evento vira PUBLICADO."""
    event_id = criar_evento(data_dir)
    requests = []

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> httpx.Response:
        requests.append((url, json))
        return httpx.Response(
            201,
            json={
                "eventId": json["eventId"],
                "created": True,
                "deliveries": 1,
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    publicados = publish_pending(
        "campanhas",
        "http://localhost:8001",
        data_dir,
    )

    assert publicados == 1
    assert len(requests) == 1
    assert requests[0][1]["eventId"] == event_id
    assert requests[0][1]["topic"] == "CampanhaPublicada"
    assert consultar_status(data_dir, event_id)[0] == "PUBLICADO"
    assert consultar_status(data_dir, event_id)[1] is not None


def test_relay_mantem_pendente_quando_broker_falha(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falha HTTP mantém evento pendente."""
    event_id = criar_evento(data_dir)

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> httpx.Response:
        return httpx.Response(
            503,
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    publicados = publish_pending(
        "campanhas",
        "http://localhost:8001",
        data_dir,
    )

    assert publicados == 0
    assert consultar_status(data_dir, event_id) == (
        "PENDENTE",
        None,
    )


def test_relay_recupera_evento_apos_falha(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Evento pendente pode ser publicado após recuperação."""
    event_id = criar_evento(data_dir)
    tentativas = 0

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> httpx.Response:
        nonlocal tentativas
        tentativas += 1

        status = 503 if tentativas == 1 else 201

        return httpx.Response(
            status,
            json={"eventId": json["eventId"]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    primeira = publish_pending(
        "campanhas",
        "http://localhost:8001",
        data_dir,
    )

    segunda = publish_pending(
        "campanhas",
        "http://localhost:8001",
        data_dir,
    )

    assert primeira == 0
    assert segunda == 1
    assert tentativas == 2
    assert consultar_status(data_dir, event_id)[0] == "PUBLICADO"


def test_relay_nao_republica_evento_confirmado(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evento publicado não deve ser enviado novamente."""
    criar_evento(data_dir)
    chamadas = 0

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1

        return httpx.Response(
            201,
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    publish_pending(
        "campanhas",
        "http://localhost:8001",
        data_dir,
    )
    publish_pending(
        "campanhas",
        "http://localhost:8001",
        data_dir,
    )

    assert chamadas == 1
