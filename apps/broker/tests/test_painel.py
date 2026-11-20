"""Testes do painel de observabilidade do broker."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from broker.app import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROKER_DISPATCH_ENABLED", "false")
    with TestClient(app) as test_client:
        yield test_client


def test_painel_vazio_retorna_json(client: TestClient) -> None:
    resposta = client.get("/painel/dados")
    assert resposta.status_code == 200
    dados = resposta.json()

    assert "summary" in dados
    assert "recentEvents" in dados
    assert "pendingDeliveries" in dados
    assert "dlq" in dados

    assert dados["summary"]["totalEvents"] == 0
    assert dados["summary"]["pendingDeliveries"] == 0
    assert dados["summary"]["dlqDeliveries"] == 0


def test_painel_html(client: TestClient) -> None:
    resposta = client.get("/painel", headers={"Accept": "text/html"})
    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]
    assert "Broker de Mensagens" in resposta.text
    assert "Eventos Recentes" in resposta.text
    assert "Dead Letter Queue" in resposta.text


def test_painel_com_eventos_e_entregas(client: TestClient) -> None:
    # Registra assinatura
    client.post(
        "/subscriptions",
        json={
            "service": "campanhas",
            "topic": "CampanhaPublicada",
            "url": "http://127.0.0.1:3002",
        },
    )

    # Publica evento com correlationId
    pub = client.post(
        "/publish",
        json={
            "eventId": "evt-123",
            "topic": "CampanhaPublicada",
            "payload": {"id": "c1"},
            "correlationId": "corr-test-1",
        },
    )
    assert pub.status_code == 201

    # Consulta painel
    dados = client.get("/painel/dados").json()
    assert dados["summary"]["totalEvents"] == 1
    assert dados["summary"]["pendingDeliveries"] == 1
    assert len(dados["recentEvents"]) == 1
    assert dados["recentEvents"][0]["eventId"] == "evt-123"
    assert dados["recentEvents"][0]["correlationId"] == "corr-test-1"
    assert len(dados["pendingDeliveries"]) == 1
    assert dados["pendingDeliveries"][0]["service"] == "campanhas"

    # HTML também renderiza o evento
    html_resp = client.get("/painel?format=html")
    assert html_resp.status_code == 200
    assert "evt-123" in html_resp.text
    assert "corr-test-1" in html_resp.text


def test_root_redirect(client: TestClient) -> None:
    # Sem text/html devolve JSON com ponteiro pro painel
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["painel"] == "/painel"

    # Com text/html redireciona
    resp_html = client.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
    assert resp_html.status_code in (302, 307)
    assert resp_html.headers["location"] == "/painel"
