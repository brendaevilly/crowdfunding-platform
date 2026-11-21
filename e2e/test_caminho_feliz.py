"""Teste E2E do caminho feliz da plataforma de crowdfunding."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

import pytest

pytestmark = pytest.mark.e2e

GATEWAY = "http://127.0.0.1:3000"


def requisicao(
    metodo: str,
    caminho: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any] | list[Any]]:
    """Executa uma requisição HTTP pelo Gateway."""

    cabecalhos = {"Content-Type": "application/json"}

    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"

    if headers:
        cabecalhos.update(headers)

    dados = json.dumps(payload).encode("utf-8") if payload is not None else None

    request = urllib.request.Request(
        f"{GATEWAY}{caminho}",
        data=dados,
        headers=cabecalhos,
        method=metodo,
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            conteudo = response.read().decode("utf-8")
            return response.status, json.loads(conteudo) if conteudo else {}

    except urllib.error.HTTPError as erro:
        conteudo = erro.read().decode("utf-8")
        return erro.code, json.loads(conteudo) if conteudo else {}


def preparar_administrador() -> str:
    """Cria ou reutiliza o administrador de teste."""
    from seed_admin import criar_admin

    administrador, _ = criar_admin(
        nome="Administrador E2E",
        email_str="admin.e2e@exemplo.com",
        senha_plana="SenhaE2eSegura123!",
        data_dir="data",
    )

    return administrador.email.valor


def obter_token(email: str, senha: str) -> str:
    """Realiza login e retorna o token JWT."""
    status_http, resposta = requisicao(
        "POST",
        "/api/identidade/login",
        payload={
            "email": email,
            "senha": senha,
        },
    )

    assert status_http == 200, f"Falha no login de {email}: {resposta}"
    assert isinstance(resposta, dict)
    assert "access_token" in resposta

    return str(resposta["access_token"])


def cadastrar_usuario(
    nome: str,
    perfil: str,
    email: str,
    senha: str,
) -> dict[str, Any]:
    """Cadastra um usuário pelo Gateway."""

    status_http, resposta = requisicao(
        "POST",
        "/api/identidade/usuarios",
        payload={
            "nome": nome,
            "email": email,
            "senha": senha,
            "perfil": perfil,
        },
    )

    assert status_http == 201, f"Falha no cadastro de {perfil}: {resposta}"
    assert isinstance(resposta, dict)
    assert resposta["perfil"] == perfil

    return resposta


def criar_usuario_autenticado(
    nome: str,
    perfil: str,
) -> tuple[dict[str, Any], str]:
    """Cria um usuário com e-mail único e obtém seu token JWT."""

    from uuid import uuid4

    email = f"{perfil.lower()}.{uuid4().hex}@exemplo.com"
    senha = "SenhaE2eSegura123!"

    usuario = cadastrar_usuario(
        nome=nome,
        perfil=perfil,
        email=email,
        senha=senha,
    )

    token = obter_token(email, senha)

    return usuario, token


def enviar_kyc(token: str, numero: str) -> dict[str, Any]:
    """Envia documento para verificação automática de identidade."""

    status_http, resposta = requisicao(
        "POST",
        "/api/identidade/kyc/documentos",
        payload={
            "tipo": "CPF",
            "numero": numero,
        },
        token=token,
    )

    assert status_http == 200, f"Falha no KYC: {resposta}"
    assert isinstance(resposta, dict)
    assert resposta["status"] == "APROVADA"

    return resposta


def consultar_notificacoes(token: str) -> list[Any]:
    """Consulta notificações do usuário."""

    status_http, resposta = requisicao(
        "GET",
        "/api/notificacoes",
        token=token,
    )

    assert status_http == 200, resposta
    assert isinstance(resposta, list)

    return resposta


def aguardar_notificacoes_retornos(
    investidores: list[tuple[dict[str, Any], str]],
    distribuicoes: list[dict[str, Any]],
    timeout: float = 30.0,
) -> None:
    """Aguarda cada investidor receber sua notificação de retorno."""

    import time

    esperados = {str(item["investidorId"]): str(item["retornoId"]) for item in distribuicoes}

    assert len(esperados) == len(investidores), (
        "Quantidade de notificações esperadas diverge dos investidores."
    )

    limite = time.monotonic() + timeout
    pendentes = set(esperados)

    while time.monotonic() < limite:
        for usuario, token in investidores:
            investidor_id = str(usuario["id"])

            if investidor_id not in pendentes:
                continue

            notificacoes = consultar_notificacoes(token)

            recebida = any(
                notificacao.get("tipoEvento") == "retorno.distribuido"
                and notificacao.get("eventoOrigemId") == esperados[investidor_id]
                for notificacao in notificacoes
            )

            if recebida:
                pendentes.remove(investidor_id)

        if not pendentes:
            print("Notificações de retorno recebidas pelos 3 investidores.")
            return

        time.sleep(0.5)

    raise AssertionError(
        f"Notificações de retorno não recebidas pelos investidores: {sorted(pendentes)}"
    )


def consultar_participacoes(token: str) -> list[Any]:
    """Consulta participações do investidor."""

    status_http, resposta = requisicao(
        "GET",
        "/api/retornos/minhas-participacoes",
        token=token,
    )

    assert status_http == 200, resposta
    assert isinstance(resposta, list)

    return resposta


def consultar_extrato_retornos(token: str) -> list[Any]:
    """Consulta retornos recebidos pelo investidor."""

    status_http, resposta = requisicao(
        "GET",
        "/api/retornos/extrato",
        token=token,
    )

    assert status_http == 200, resposta
    assert isinstance(resposta, list)

    return resposta


def criar_aporte(
    campanha_id: str,
    investidor_id: str,
    valor: int,
    chave: str,
    token: str,
) -> dict[str, Any]:
    """Realiza um aporte pelo Gateway com chave de idempotência."""

    status_http, resposta = requisicao(
        "POST",
        "/api/aportes",
        payload={
            "campanhaId": campanha_id,
            "investidorId": investidor_id,
            "valor": valor,
        },
        token=token,
        headers={
            "Idempotency-Key": chave,
        },
    )

    assert status_http == 201, f"Falha ao realizar aporte de {valor} centavos: {resposta}"

    assert isinstance(resposta, dict)

    return resposta


def criar_e_publicar_campanha(
    token_empreendedor: str,
    token_admin: str,
) -> dict[str, Any]:
    """Cria, submete e aprova uma campanha pelo Gateway."""

    from datetime import UTC, datetime, timedelta

    agora = datetime.now(UTC)

    status_http, resposta = requisicao(
        "POST",
        "/api/campanhas",
        payload={
            "titulo": "Projeto E2E - Horta Comunitaria",
            "descricao": "Campanha de teste ponta a ponta.",
            "meta": 300000,
            "prazoInicio": agora.isoformat(),
            "prazoFim": (agora + timedelta(days=2)).isoformat(),
        },
        token=token_empreendedor,
    )

    assert status_http == 201, f"Falha ao criar campanha: {resposta}"
    assert isinstance(resposta, dict)

    campanha_id = str(resposta["id"])

    status_http, resposta = requisicao(
        "POST",
        f"/api/campanhas/{campanha_id}/submeter",
        token=token_empreendedor,
    )

    assert status_http == 200, f"Falha ao submeter campanha: {resposta}"

    status_http, resposta = requisicao(
        "POST",
        f"/api/campanhas/{campanha_id}/aprovar",
        token=token_admin,
    )

    assert status_http == 200, f"Falha ao aprovar campanha: {resposta}"

    assert isinstance(resposta, dict)

    return resposta


def aguardar_investidor_verificado(
    investidor_id: str,
    timeout: float = 20.0,
) -> None:
    """Aguarda o consumidor de KYC registrar o investidor em Aportes."""

    import sqlite3
    import time

    limite = time.monotonic() + timeout

    while time.monotonic() < limite:
        with sqlite3.connect("data/aportes.db") as conn:
            registro = conn.execute(
                """
                SELECT 1
                FROM investidor_verificado
                WHERE investidor_id = ?
                """,
                (investidor_id,),
            ).fetchone()

        if registro is not None:
            return

        time.sleep(0.2)

    raise AssertionError(
        f"Investidor {investidor_id} não foi verificado em Aportes após {timeout} segundos."
    )


def preparar_investidores() -> list[tuple[dict[str, Any], str]]:
    """Cadastra três investidores e verifica seus KYC automáticos."""

    investidores = []

    for indice in range(1, 4):
        usuario, token = criar_usuario_autenticado(
            nome=f"Investidor E2E {indice}",
            perfil="INVESTIDOR",
        )

        numero_documento = f"1234567890{indice}"

        verificacao = enviar_kyc(
            token,
            numero_documento,
        )

        assert verificacao["status"] == "APROVADA"

        aguardar_investidor_verificado(
            str(usuario["id"]),
        )

        investidores.append((usuario, token))

    return investidores


def realizar_aportes(
    campanha_id: str,
    investidores: list[tuple[dict[str, Any], str]],
) -> int:
    """Realiza três aportes e retorna o total arrecadado."""

    valores = [
        120000,
        100000,
        80000,
    ]

    total = 0

    for indice, ((usuario, _token), valor) in enumerate(
        zip(investidores, valores, strict=True),
        start=1,
    ):
        criar_aporte(
            campanha_id=campanha_id,
            investidor_id=str(usuario["id"]),
            valor=valor,
            chave=f"e2e-{campanha_id}-investidor-{indice}",
            token=_token,
        )

        total += valor

        print(f"Aporte {indice} confirmado: {valor / 100:.2f} reais")

    assert total == 300000

    return total


def aguardar_usuario_no_cache(
    usuario_id: str,
    timeout: float = 15.0,
) -> None:
    """Aguarda a projeção do usuário no serviço de campanhas."""

    import sqlite3
    import time

    limite = time.monotonic() + timeout

    while time.monotonic() < limite:
        with sqlite3.connect("data/campanhas.db") as conn:
            usuario = conn.execute(
                """
                SELECT perfil, status
                FROM usuarios_cache
                WHERE usuario_id = ?
                """,
                (usuario_id,),
            ).fetchone()

        if usuario == ("EMPREENDEDOR", "ATIVO"):
            return

        time.sleep(0.1)

    raise AssertionError(
        f"Usuário {usuario_id} não foi sincronizado em Campanhas após 15 segundos."
    )


def aguardar_campanha_na_custodia(
    campanha_id: str,
    timeout: float = 20.0,
) -> None:
    """Aguarda a Custódia processar o evento de campanha publicada."""

    import sqlite3
    import time

    limite = time.monotonic() + timeout

    while time.monotonic() < limite:
        with sqlite3.connect("data/custodia_retornos.db") as conn:
            registro = conn.execute(
                """
                SELECT campanha_id
                FROM custodia_contas
                WHERE campanha_id = ?
                """,
                (campanha_id,),
            ).fetchone()

        if registro is not None:
            print(f"Campanha {campanha_id} sincronizada na Custódia.")
            return

        time.sleep(0.2)

    raise AssertionError(
        f"Campanha {campanha_id} não foi sincronizada na Custódia após {timeout} segundos."
    )


def test_caminho_feliz_completo(sistema_e2e) -> None:
    """Executa o fluxo principal da plataforma pelo Gateway."""

    email_admin = preparar_administrador()
    token_admin = obter_token(
        email_admin,
        "SenhaE2eSegura123!",
    )

    empreendedor, token_empreendedor = criar_usuario_autenticado(
        nome="Empreendedor E2E",
        perfil="EMPREENDEDOR",
    )

    aguardar_usuario_no_cache(empreendedor["id"])

    investidores = preparar_investidores()

    campanha = criar_e_publicar_campanha(
        token_empreendedor,
        token_admin,
    )

    campanha_id = str(campanha["id"])

    aguardar_campanha_na_custodia(campanha_id)

    total = realizar_aportes(
        campanha_id,
        investidores,
    )

    assert total == 300000

    # Aguarda a projeção assíncrona dos três aportes em Campanhas.
    aguardar_total_arrecadado(
        campanha_id,
        valor_esperado=total,
    )

    aguardar_retencoes_custodia(
        campanha_id,
        valor_esperado=total,
        quantidade_esperada=3,
    )

    prazo_fim = campanha.get("prazoFim") or campanha.get("prazo_fim")

    assert isinstance(prazo_fim, str), f"Prazo final da campanha não encontrado: {campanha}"

    aguardar_liquidacao_sucesso(
        campanha_id,
        prazo_fim,
    )

    print(f"Campanha {campanha_id} criada por {empreendedor['nome']}")

    print("Cadastro, publicação e aportes concluídos.")

    distribuir_retornos_e_validar(
        campanha_id=campanha_id,
        token_empreendedor=token_empreendedor,
        total=total,
        investidores=investidores,
    )


def avancar_relogio(segundos: int) -> dict[str, Any]:
    """Avança o relógio da Custódia e executa a apuração."""

    dados = json.dumps({"seconds": segundos}).encode("utf-8")

    request = urllib.request.Request(
        "http://127.0.0.1:3004/_dev/clock/advance",
        data=dados,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        resultado = json.loads(response.read().decode("utf-8"))

    assert isinstance(resultado, dict)
    assert resultado["apuradas"] >= 1

    return resultado


def consultar_extrato_custodia(
    campanha_id: str,
) -> dict[str, Any]:
    """Consulta o extrato financeiro da Custódia."""

    url = f"http://127.0.0.1:3004/custodia/campanhas/{campanha_id}/extrato"

    request = urllib.request.Request(url, method="GET")

    with urllib.request.urlopen(request, timeout=10) as response:
        resultado = json.loads(response.read().decode("utf-8"))

    assert isinstance(resultado, dict)
    return resultado


def aguardar_total_arrecadado(
    campanha_id: str,
    valor_esperado: int,
    timeout: float = 30.0,
) -> None:
    """Aguarda Campanhas processar todos os eventos de aportes."""

    import sqlite3
    import time

    limite = time.monotonic() + timeout

    while time.monotonic() < limite:
        with sqlite3.connect("data/campanhas.db") as conn:
            registro = conn.execute(
                """
                SELECT valor_arrecadado
                FROM campanhas
                WHERE id = ?
                """,
                (campanha_id,),
            ).fetchone()

        if registro is not None and int(registro[0]) >= valor_esperado:
            print(f"Total sincronizado em Campanhas: R$ {int(registro[0]) / 100:.2f}")
            return

        time.sleep(0.2)

    raise AssertionError(
        f"Campanha {campanha_id} não recebeu todos os aportes. "
        f"Valor esperado: {valor_esperado} centavos."
    )


def aguardar_retencoes_custodia(
    campanha_id: str,
    valor_esperado: int,
    quantidade_esperada: int,
    timeout: float = 30.0,
) -> None:
    """Aguarda a Custódia registrar todos os aportes confirmados."""

    import time

    url = f"http://127.0.0.1:3004/custodia/campanhas/{campanha_id}/extrato"

    limite = time.monotonic() + timeout

    while time.monotonic() < limite:
        try:
            with urllib.request.urlopen(
                url,
                timeout=5,
            ) as response:
                extrato = json.loads(response.read().decode("utf-8"))

            retencoes = [
                movimentacao
                for movimentacao in extrato.get("movimentacoes", [])
                if movimentacao.get("tipo") == "RETENCAO"
            ]

            total_retido = sum(int(movimentacao["valor"]) for movimentacao in retencoes)

            if len(retencoes) == quantidade_esperada and total_retido == valor_esperado:
                print(
                    f"Custódia sincronizada: "
                    f"{len(retencoes)} retenções, "
                    f"R$ {total_retido / 100:.2f}"
                )
                return

        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ):
            pass

        time.sleep(0.2)

    raise AssertionError(
        f"Custódia não registrou todos os aportes da campanha "
        f"{campanha_id}. Esperado: {quantidade_esperada} retenções "
        f"e {valor_esperado} centavos."
    )


def aguardar_liquidacao_sucesso(
    campanha_id: str,
    prazo_fim: str,
    timeout: float = 40.0,
) -> None:
    """Avança o relógio de desenvolvimento e aguarda a liquidação real."""

    import time
    from datetime import UTC, datetime

    prazo = datetime.fromisoformat(prazo_fim.replace("Z", "+00:00"))

    segundos = max(
        1.0,
        (prazo - datetime.now(UTC)).total_seconds() + 60.0,
    )

    url = "http://127.0.0.1:3004/_dev/clock/advance"

    dados = json.dumps({"seconds": segundos}).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=dados,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            resultado = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8")
        raise AssertionError(f"Falha ao avançar relógio da Custódia: {detalhe}") from erro

    print(f"Relógio avançado. Campanhas apuradas: {resultado.get('apuradas')}")

    url_extrato = f"http://127.0.0.1:3004/custodia/campanhas/{campanha_id}/extrato"

    limite = time.monotonic() + timeout

    while time.monotonic() < limite:
        try:
            with urllib.request.urlopen(
                url_extrato,
                timeout=5,
            ) as response:
                extrato = json.loads(response.read().decode("utf-8"))

            liquidacao = extrato.get("liquidacao")

            if liquidacao is not None:
                assert liquidacao["resultado"] == "SUCESSO", f"Resultado inesperado: {liquidacao}"

                assert liquidacao["valor_bruto"] == 300000
                assert liquidacao["taxa_plataforma"] == 15000
                assert liquidacao["valor_liquido"] == 285000
                assert extrato["saldo_retido"] == 0

                print("Campanha liquidada com sucesso.")
                print("Valor bruto: R$ 3.000,00")
                print("Taxa: R$ 150,00")
                print("Valor líquido: R$ 2.850,00")
                return

        except urllib.error.URLError:
            pass

        time.sleep(0.5)

    raise AssertionError(f"Campanha {campanha_id} não foi liquidada após {timeout} segundos.")


def aguardar_participacoes(
    campanha_id: str,
    investidores: list[tuple[dict[str, Any], str]],
    timeout: float = 30.0,
) -> None:
    """Aguarda a projeção assíncrona das participações após a liquidação."""

    limite = time.time() + timeout
    pendentes = {str(usuario["id"]): token for usuario, token in investidores}

    while time.time() < limite:
        for investidor_id, token in list(pendentes.items()):
            participacoes = consultar_participacoes(token)
            if any(
                campanha_id in (item.get("campanhaId"), item.get("campanha_id"))
                for item in participacoes
                if isinstance(item, dict)
            ):
                del pendentes[investidor_id]

        if not pendentes:
            print("Participações registradas para os 3 investidores.")
            return

        time.sleep(0.5)

    raise AssertionError(
        f"Participações não registradas após {timeout} segundos: {sorted(pendentes)}"
    )


def distribuir_retornos_e_validar(
    campanha_id: str,
    token_empreendedor: str,
    total: int,
    investidores: list[tuple[dict[str, Any], str]],
) -> None:
    """Distribui retornos e valida os valores proporcionais."""

    valor_distribuicao = total - (total * 5 // 100)

    aguardar_participacoes(campanha_id, investidores)

    status_http, resposta = requisicao(
        "POST",
        f"/api/retornos/campanhas/{campanha_id}/distribuir",
        payload={
            "valorTotal": valor_distribuicao,
        },
        token=token_empreendedor,
    )

    assert status_http == 200, f"Falha na distribuição de retornos: {resposta}"

    assert isinstance(resposta, dict)

    distribuicoes = resposta["distribuicoes"]

    assert isinstance(distribuicoes, list)
    assert len(distribuicoes) == 3

    valores = {str(item["investidorId"]): int(item["valor"]) for item in distribuicoes}

    assert sum(valores.values()) == valor_distribuicao

    assert set(valores) == {str(usuario["id"]) for usuario, _token in investidores}

    assert all(item.get("retornoId") for item in distribuicoes), (
        "Distribuição sem identificador de retorno."
    )

    print("Distribuição proporcional validada.")

    aguardar_notificacoes_retornos(
        investidores,
        distribuicoes,
    )
