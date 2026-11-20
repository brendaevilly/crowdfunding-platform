"""Testes de entrega da interface web (frontend) servida pelo Gateway (#32)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gateway.app import criar_app


def test_obter_pagina_inicial_html() -> None:
    """Verifica que o Gateway serve a interface HTML principal na raiz com status 200."""
    app = criar_app()
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        conteudo = resp.text

        # Valida que todos os formulários e seções exigidos estão presentes no HTML
        assert 'id="form-cadastro"' in conteudo
        assert 'id="form-login"' in conteudo
        assert 'id="form-kyc"' in conteudo
        assert 'id="campanhas-container"' in conteudo
        assert 'id="form-aporte"' in conteudo
        assert 'id="aporte-idempotency-key"' in conteudo
        assert 'id="tabela-aportes-container"' in conteudo
        assert 'id="lista-notificacoes-container"' in conteudo


def test_obter_estilos_css() -> None:
    """Verifica entrega dos arquivos de estilo estáticos com MIME type correto."""
    app = criar_app()
    with TestClient(app) as client:
        resp = client.get("/static/styles.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]
        assert ":root" in resp.text
        assert ".progress-bar-fill" in resp.text


def test_obter_script_js() -> None:
    """Verifica entrega do script JavaScript com rotas das APIs integradas."""
    app = criar_app()
    with TestClient(app) as client:
        resp = client.get("/static/app.js")
        assert resp.status_code == 200
        assert "application/javascript" in resp.headers["content-type"]
        script = resp.text

        # Verifica chamadas essenciais para o fluxo do investidor
        assert "/api/identidade/usuarios" in script
        assert "/api/identidade/login" in script
        assert "/api/identidade/kyc/documentos" in script
        assert "/api/campanhas" in script
        assert "/api/aportes" in script
        assert "/api/notificacoes" in script
        assert "Idempotency-Key" in script


def test_arquivo_estatico_inexistente_retorna_404() -> None:
    """Tentativa de buscar arquivo inexistente na pasta static retorna 404."""
    app = criar_app()
    with TestClient(app) as client:
        resp = client.get("/static/arquivo_inexistente.xyz")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "nao_encontrado"


def test_path_traversal_na_pasta_estatica_rejeitado() -> None:
    """Tentativas de path traversal são rejeitadas com 403 ou 404."""
    app = criar_app()
    with TestClient(app) as client:
        resp = client.get("/static/../pyproject.toml")
        # FastAPI/Starlette ou o handler do Gateway bloqueia antes de vazar
        assert resp.status_code in (403, 404)


def test_paginas_separadas_login_e_cadastro() -> None:
    """Verifica que /login e /cadastro (e seus .html) são servidos em páginas dedicadas."""
    app = criar_app()
    with TestClient(app) as client:
        resp_login = client.get("/login")
        assert resp_login.status_code == 200
        assert "Entrar na sua conta" in resp_login.text

        resp_cad = client.get("/cadastro")
        assert resp_cad.status_code == 200
        assert "Criar sua conta" in resp_cad.text

        resp_camp = client.get("/campanha.html")
        assert resp_camp.status_code == 200
        assert "Detalhes da Campanha" in resp_camp.text

        resp_apo = client.get("/aporte.html")
        assert resp_apo.status_code == 200
        assert "Contribua com o projeto" in resp_apo.text

        resp_dash = client.get("/dashboard.html")
        assert resp_dash.status_code == 200
        assert "Meu Painel de Investimentos" in resp_dash.text
