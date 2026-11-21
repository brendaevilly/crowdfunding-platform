#!/usr/bin/env python3
"""Seed de demonstração: admin, empreendedor, investidores e uma campanha publicada com aportes.

Requer o sistema no ar (`make dev` em outro terminal). Os dados passam pelo gateway
(mesmos caminhos da interface), então o estado fica consistente em todos os serviços.
É idempotente: usuários existentes são reaproveitados e a campanha de demonstração
só é criada uma vez.

    make seed
    uv run python scripts/seed_demo.py [--gateway http://127.0.0.1:3000]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from seed_admin import criar_admin

SENHA = "SenhaDemo1234!"
ADMIN = ("Administrador Demo", "admin@aporta.demo")
EMPREENDEDOR = ("Empreendedora Demo", "empreendedora@aporta.demo")
INVESTIDORES = [
    ("Investidor Demo 1", "investidor1@aporta.demo", "12345678901", 120_000),
    ("Investidor Demo 2", "investidor2@aporta.demo", "12345678902", 80_000),
    ("Investidor Demo 3", "investidor3@aporta.demo", "12345678903", 50_000),
]
CAMPANHA_TITULO = "Laboratório Maker na Escola Pública (demo)"
META_CENTAVOS = 1_000_000


class Cliente:
    def __init__(self, gateway: str) -> None:
        self.gateway = gateway.rstrip("/")

    def chamar(
        self,
        metodo: str,
        caminho: str,
        payload: dict[str, Any] | None = None,
        token: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        cabecalhos = {"Content-Type": "application/json", **(headers or {})}
        if token:
            cabecalhos["Authorization"] = f"Bearer {token}"
        dados = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.gateway}{caminho}", data=dados, headers=cabecalhos, method=metodo
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as resposta:
                corpo = resposta.read().decode("utf-8")
                return resposta.status, json.loads(corpo) if corpo else {}
        except urllib.error.HTTPError as erro:
            corpo = erro.read().decode("utf-8")
            return erro.code, json.loads(corpo) if corpo else {}


def aguardar_gateway(cliente: Cliente, timeout: float = 60.0) -> None:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        try:
            with urllib.request.urlopen(f"{cliente.gateway}/health", timeout=15) as resposta:
                if resposta.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise SystemExit("Gateway fora do ar. Suba o sistema com `make dev` e tente de novo.")


def garantir_usuario(cliente: Cliente, nome: str, email: str, perfil: str) -> tuple[str, str]:
    """Cadastra (se preciso), faz login e devolve (id, token)."""
    status, resposta = cliente.chamar(
        "POST",
        "/api/identidade/usuarios",
        {"nome": nome, "email": email, "senha": SENHA, "perfil": perfil},
    )
    if status not in (201, 409):
        raise SystemExit(f"Falha ao cadastrar {email}: {status} {resposta}")
    status, resposta = cliente.chamar(
        "POST", "/api/identidade/login", {"email": email, "senha": SENHA}
    )
    if status != 200:
        raise SystemExit(f"Falha no login de {email}: {status} {resposta}")
    token = str(resposta["access_token"])
    status, me = cliente.chamar("GET", "/api/identidade/usuarios/me", token=token)
    if status != 200:
        raise SystemExit(f"Falha ao consultar {email}: {status} {me}")
    return str(me["id"]), token


def campanha_existente(cliente: Cliente, token: str) -> dict[str, Any] | None:
    status, resposta = cliente.chamar("GET", "/api/campanhas", token=token)
    if status != 200:
        return None
    itens = resposta if isinstance(resposta, list) else resposta.get("campanhas", [])
    for item in itens:
        if isinstance(item, dict) and item.get("titulo") == CAMPANHA_TITULO:
            return item
    return None


def criar_campanha(cliente: Cliente, token_empreendedor: str, token_admin: str) -> dict[str, Any]:
    agora = datetime.now(UTC)
    payload = {
        "titulo": CAMPANHA_TITULO,
        "descricao": "Kits de robótica e impressão 3D para uma escola da rede pública.",
        "meta": META_CENTAVOS,
        "prazoInicio": agora.isoformat(),
        "prazoFim": (agora + timedelta(days=30)).isoformat(),
    }
    # A projeção do empreendedor em Campanhas é assíncrona: tenta até propagar.
    limite = time.monotonic() + 30
    while True:
        status, campanha = cliente.chamar("POST", "/api/campanhas", payload, token_empreendedor)
        if status == 201:
            break
        if time.monotonic() > limite:
            raise SystemExit(f"Falha ao criar campanha: {status} {campanha}")
        time.sleep(1)
    campanha_id = str(campanha["id"])
    status, resposta = cliente.chamar(
        "POST", f"/api/campanhas/{campanha_id}/submeter", token=token_empreendedor
    )
    if status != 200:
        raise SystemExit(f"Falha ao submeter campanha: {status} {resposta}")
    status, resposta = cliente.chamar(
        "POST", f"/api/campanhas/{campanha_id}/aprovar", token=token_admin
    )
    if status != 200:
        raise SystemExit(f"Falha ao aprovar campanha: {status} {resposta}")
    return dict(resposta)


def main() -> None:
    parser = argparse.ArgumentParser(description="Popula o sistema com dados de demonstração.")
    parser.add_argument("--gateway", default="http://127.0.0.1:3000")
    parser.add_argument("--data-dir", default="data", help="Diretório dos bancos SQLite.")
    args = parser.parse_args()

    cliente = Cliente(args.gateway)
    aguardar_gateway(cliente)

    admin, _criado = criar_admin(
        nome=ADMIN[0], email_str=ADMIN[1], senha_plana=SENHA, data_dir=args.data_dir
    )
    print(f"admin:         {ADMIN[1]} (id {admin.id})")
    status, resposta = cliente.chamar(
        "POST", "/api/identidade/login", {"email": ADMIN[1], "senha": SENHA}
    )
    if status != 200:
        raise SystemExit(f"Falha no login do admin: {status} {resposta}")
    token_admin = str(resposta["access_token"])

    _id_emp, token_emp = garantir_usuario(cliente, *EMPREENDEDOR, "EMPREENDEDOR")
    print(f"empreendedor:  {EMPREENDEDOR[1]}")

    investidores: list[tuple[str, str, int]] = []
    for nome, email, cpf, valor in INVESTIDORES:
        id_inv, token_inv = garantir_usuario(cliente, nome, email, "INVESTIDOR")
        status, resposta = cliente.chamar(
            "POST",
            "/api/identidade/kyc/documentos",
            {"tipo": "CPF", "numero": cpf},
            token_inv,
        )
        print(f"investidor:    {email} (KYC {resposta.get('status', status)})")
        investidores.append((id_inv, token_inv, valor))

    campanha = campanha_existente(cliente, token_admin)
    if campanha is not None:
        print(f"campanha:      já existe ({campanha['id']}); nada a criar.")
        return

    campanha = criar_campanha(cliente, token_emp, token_admin)
    campanha_id = str(campanha["id"])
    print(f"campanha:      {CAMPANHA_TITULO} ({campanha_id}) PUBLICADA")

    time.sleep(3)  # propagação de campanha.publicada e identidade.verificada
    for indice, (id_inv, token_inv, valor) in enumerate(investidores, start=1):
        status, resposta = cliente.chamar(
            "POST",
            "/api/aportes",
            {"campanhaId": campanha_id, "investidorId": id_inv, "valor": valor},
            token_inv,
            {"Idempotency-Key": f"seed-demo-{campanha_id}-{indice}"},
        )
        print(f"aporte {indice}:      R$ {valor / 100:.2f} -> HTTP {status}")

    print(f"\nPronto. Senha de todos os usuários de demonstração: {SENHA}")
    print("Interface: http://127.0.0.1:3000")


if __name__ == "__main__":
    main()
