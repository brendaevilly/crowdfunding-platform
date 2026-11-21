"""E2E de falha e resiliência (#36): RNF2, RNF7 e garantias dos contratos."""

from __future__ import annotations

import http.client
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from e2e.test_caminho_feliz import (
    aguardar_campanha_na_custodia,
    aguardar_liquidacao_sucesso,
    aguardar_retencoes_custodia,
    aguardar_usuario_no_cache,
    avancar_relogio,
    consultar_extrato_custodia,
    criar_aporte,
    criar_e_publicar_campanha,
    criar_usuario_autenticado,
    obter_token,
    preparar_administrador,
    preparar_investidores,
    requisicao,
)

pytestmark = pytest.mark.e2e

RAIZ = Path(__file__).resolve().parents[1]
BROKER = "http://127.0.0.1:3010"
CUSTODIA = "http://127.0.0.1:3004"
CAMPANHAS = "http://127.0.0.1:3002"
SERVICOS = [f"http://127.0.0.1:{porta}" for porta in (3001, 3002, 3003, 3004, 3005, 3010)]

Investidores = list[tuple[dict[str, Any], str]]


# ----------------------------------------------------------------------------- utilitários


def controlar(comando: str, servico: str) -> None:
    """Derruba (kill) ou sobe (start) um serviço pelo launcher scripts/dev.py."""
    resultado = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "dev.py"), comando, servico],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert resultado.returncode == 0, f"dev.py {comando} {servico}: {resultado.stdout}"


def servico_responde(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=5) as resposta:
            return int(resposta.status) == 200
    except (OSError, urllib.error.URLError):
        return False


def aguardar_servico(url: str, timeout: float = 40.0) -> None:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if servico_responde(url):
            return
        time.sleep(0.5)
    raise AssertionError(f"Serviço {url} não voltou em {timeout} segundos.")


def aguardar_servico_fora(url: str, timeout: float = 20.0) -> None:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if not servico_responde(url):
            return
        time.sleep(0.3)
    raise AssertionError(f"Serviço {url} continua no ar após o kill.")


def aguardar_sistema_pronto() -> None:
    """Garante que todos os microsserviços respondem antes de iniciar o cenário."""
    for url in SERVICOS:
        aguardar_servico(url, timeout=60)

    # O Gateway só está pronto quando consegue repassar chamadas ao serviço de Identidade.
    limite = time.monotonic() + 60
    while time.monotonic() < limite:
        try:
            requisicao(
                "POST",
                "/api/identidade/login",
                payload={"email": "pronto@exemplo.com", "senha": "invalida"},
            )
            return
        except (OSError, urllib.error.URLError, http.client.HTTPException):
            time.sleep(1)
    raise AssertionError("Gateway não repassou chamadas à Identidade em 60 segundos.")


def http_json(
    metodo: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    dados = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=dados,
        headers={"Content-Type": "application/json"},
        method=metodo,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as resposta:
            conteudo = resposta.read().decode("utf-8")
            return resposta.status, json.loads(conteudo) if conteudo else {}
    except urllib.error.HTTPError as erro:
        conteudo = erro.read().decode("utf-8")
        return erro.code, json.loads(conteudo) if conteudo else {}


def movimentacoes(campanha_id: str, tipo: str) -> list[dict[str, Any]]:
    extrato = consultar_extrato_custodia(campanha_id)
    return [m for m in extrato.get("movimentacoes", []) if m.get("tipo") == tipo]


def preparar_campanha() -> tuple[Investidores, str, str, str]:
    """Cria 3 investidores com KYC e uma campanha publicada (meta R$ 3.000,00).

    Retorna (investidores, campanha_id, prazo_fim, token_admin).
    """
    aguardar_sistema_pronto()
    token_admin = obter_token(preparar_administrador(), "SenhaE2eSegura123!")
    empreendedor, token_empreendedor = criar_usuario_autenticado(
        nome="Empreendedor E2E Falha",
        perfil="EMPREENDEDOR",
    )
    # A projeção do usuário em Campanhas é assíncrona.
    aguardar_usuario_no_cache(str(empreendedor["id"]))
    investidores = preparar_investidores()
    campanha = criar_e_publicar_campanha(token_empreendedor, token_admin)
    campanha_id = str(campanha["id"])
    prazo_fim = campanha.get("prazoFim") or campanha.get("prazo_fim")
    assert isinstance(prazo_fim, str)
    aguardar_campanha_na_custodia(campanha_id)
    return investidores, campanha_id, prazo_fim, token_admin


def aportar(campanha_id: str, investidores: Investidores, valores: list[int]) -> None:
    for indice, ((usuario, token), valor) in enumerate(
        zip(investidores, valores, strict=False), start=1
    ):
        criar_aporte(
            campanha_id=campanha_id,
            investidor_id=str(usuario["id"]),
            valor=valor,
            chave=f"e2e-falha-{campanha_id}-{indice}",
            token=token,
        )


# ----------------------------------------------------------------------------- cenários


def test_meta_nao_atingida_devolve_integral(sistema_e2e: object) -> None:
    """Meta não atingida: devolução integral, campanha ENCERRADA, nenhuma liberação."""
    investidores, campanha_id, _prazo, token_admin = preparar_campanha()

    aportar(campanha_id, investidores, [80_000, 50_000])  # R$ 1.300 < meta R$ 3.000
    aguardar_retencoes_custodia(campanha_id, valor_esperado=130_000, quantidade_esperada=2)

    avancar_relogio(3 * 24 * 3600)

    limite = time.monotonic() + 40
    extrato: dict[str, Any] = {}
    while time.monotonic() < limite:
        extrato = consultar_extrato_custodia(campanha_id)
        if extrato.get("liquidacao") is not None:
            break
        time.sleep(0.5)

    liquidacao = extrato["liquidacao"]
    assert liquidacao is not None, "Campanha não foi liquidada."
    assert liquidacao["resultado"] == "FALHA"
    assert liquidacao["taxa_plataforma"] == 0
    assert extrato["saldo_retido"] == 0

    devolucoes = movimentacoes(campanha_id, "DEVOLUCAO")
    assert sum(int(m["valor"]) for m in devolucoes) == 130_000
    assert len(devolucoes) == 2
    assert movimentacoes(campanha_id, "LIBERACAO") == []
    assert movimentacoes(campanha_id, "TAXA") == []

    # Campanhas é encerrada sem atingir a meta (eventual, via campanha.resultado).
    limite = time.monotonic() + 30
    campanha: Any = {}
    while time.monotonic() < limite:
        _status, campanha = requisicao("GET", f"/api/campanhas/{campanha_id}", token=token_admin)
        if isinstance(campanha, dict) and campanha.get("status") == "ENCERRADA":
            break
        time.sleep(0.5)
    assert campanha.get("status") == "ENCERRADA"
    assert campanha.get("metaAtingida") is False


def test_custodia_fora_durante_aportes_sem_retencao_duplicada(sistema_e2e: object) -> None:
    """Custódia indisponível: eventos acumulam no broker e são processados na volta."""
    investidores, campanha_id, prazo_fim, _token_admin = preparar_campanha()

    controlar("kill", "custodia_retornos")
    aguardar_servico_fora(CUSTODIA)

    aportar(campanha_id, investidores, [120_000, 100_000, 80_000])  # aceitos sem a Custódia
    time.sleep(3)  # dá tempo de o broker tentar (e falhar) a entrega

    controlar("start", "custodia_retornos")
    aguardar_servico(CUSTODIA)

    aguardar_retencoes_custodia(
        campanha_id, valor_esperado=300_000, quantidade_esperada=3, timeout=60
    )

    # Sem retenção duplicada mesmo após novas tentativas/reentregas.
    time.sleep(4)
    retencoes = movimentacoes(campanha_id, "RETENCAO")
    assert len(retencoes) == 3
    assert sum(int(m["valor"]) for m in retencoes) == 300_000

    aguardar_liquidacao_sucesso(campanha_id, prazo_fim)


def test_campanhas_fora_rejeita_aportes(sistema_e2e: object) -> None:
    """Campanhas indisponível: aportes rejeitados (503) e sem inconsistência na Custódia."""
    investidores, campanha_id, _prazo, _token_admin = preparar_campanha()
    usuario, token = investidores[0]

    controlar("kill", "campanhas")
    aguardar_servico_fora(CAMPANHAS)

    try:
        for indice in range(3):  # também exercita o circuit breaker
            status_http, resposta = requisicao(
                "POST",
                "/api/aportes",
                payload={
                    "campanhaId": campanha_id,
                    "investidorId": str(usuario["id"]),
                    "valor": 50_000,
                },
                token=token,
                headers={"Idempotency-Key": f"e2e-campanhas-fora-{uuid4().hex}-{indice}"},
            )
            assert status_http == 503, f"Esperado 503, obtido {status_http}: {resposta}"
            assert isinstance(resposta, dict)
            assert resposta.get("status") == "REJEITADO"
    finally:
        controlar("start", "campanhas")
        aguardar_servico(CAMPANHAS)

    time.sleep(3)
    extrato = consultar_extrato_custodia(campanha_id)
    assert extrato["saldo_retido"] == 0
    assert movimentacoes(campanha_id, "RETENCAO") == []


def test_reinicio_do_broker_nada_se_perde(sistema_e2e: object) -> None:
    """Broker reiniciado no meio do fluxo: nenhum evento é perdido nem duplicado."""
    investidores, campanha_id, prazo_fim, _token_admin = preparar_campanha()

    aportar(campanha_id, investidores[:1], [120_000])

    controlar("kill", "broker")
    aguardar_servico_fora(BROKER)

    # Aportes seguem sendo aceitos; os eventos ficam na outbox até o broker voltar.
    for indice, valor in ((2, 100_000), (3, 80_000)):
        usuario, token = investidores[indice - 1]
        criar_aporte(
            campanha_id=campanha_id,
            investidor_id=str(usuario["id"]),
            valor=valor,
            chave=f"e2e-broker-{campanha_id}-{indice}",
            token=token,
        )

    time.sleep(3)
    controlar("start", "broker")
    aguardar_servico(BROKER)

    aguardar_retencoes_custodia(
        campanha_id, valor_esperado=300_000, quantidade_esperada=3, timeout=60
    )

    time.sleep(4)
    assert len(movimentacoes(campanha_id, "RETENCAO")) == 3

    aguardar_liquidacao_sucesso(campanha_id, prazo_fim)


def test_evento_envenenado_cai_na_dlq_e_replay(sistema_e2e: object) -> None:
    """Evento inválido esgota as tentativas, vai para a DLQ e pode sofrer replay."""
    aguardar_sistema_pronto()
    evento_id = str(uuid4())

    status_http, _ = http_json(
        "POST",
        f"{BROKER}/publish",
        {
            "eventId": evento_id,
            "topic": "aporte.confirmado",
            "payload": {"campo_invalido": True},
            "correlationId": evento_id,
        },
    )
    assert status_http == 201

    def aguardar_dlq(timeout: float, delivery_id: int | None = None) -> dict[str, Any]:
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            _status, itens = http_json("GET", f"{BROKER}/dlq")
            for item in itens:
                if item["eventId"] != evento_id:
                    continue
                if delivery_id is None or item["id"] == delivery_id:
                    return dict(item)
            time.sleep(0.5)
        raise AssertionError("Evento envenenado não chegou na DLQ.")

    item = aguardar_dlq(timeout=90)
    assert item["service"]
    assert item["attempts"] >= 1
    assert "422" in str(item["lastError"])

    # Replay: a entrega volta para a fila e é reprocessada (e, sendo inválida, retorna à DLQ).
    status_http, resposta = http_json("POST", f"{BROKER}/dlq/{item['id']}/replay")
    assert status_http == 200
    assert resposta["replayed"] is True

    item_replay = aguardar_dlq(timeout=90, delivery_id=item["id"])
    assert item_replay["id"] == item["id"]
    assert servico_responde(CUSTODIA), "A Custódia deve seguir saudável após o evento envenenado."
