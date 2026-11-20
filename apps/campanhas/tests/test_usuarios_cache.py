"""Testes de consumo de eventos e cache local de usuários."""

from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from campanhas.repository import inicializar_banco
from campanhas.usuarios_cache import (
    consumir_usuario_cadastrado,
    consumir_usuario_status_alterado,
    verificar_apto_a_criar_campanha,
)
from shared.db import open_db


def test_ciclo_de_vida_usuario_cache(tmp_path: Path) -> None:
    inicializar_banco(tmp_path)

    with closing(open_db("campanhas", tmp_path)) as conn:
        # 1. Usuário desconhecido não pode criar campanha
        apto, motivo = verificar_apto_a_criar_campanha(conn, "usr-1")
        assert not apto
        assert "não encontrado" in (motivo or "")

        # 2. Cadastro de empreendedor chega (fica ATIVO na plataforma)
        consumir_usuario_cadastrado(
            conn,
            {
                "usuarioId": "usr-1",
                "perfil": "EMPREENDEDOR",
                "cadastradoEm": datetime(2026, 1, 1, 12, 0, tzinfo=UTC).isoformat(),
            },
        )

        apto, motivo = verificar_apto_a_criar_campanha(conn, "usr-1")
        assert apto
        assert motivo is None

        # 3. Bloqueio do usuário impede novas campanhas
        consumir_usuario_status_alterado(
            conn,
            {
                "usuarioId": "usr-1",
                "statusAnterior": "ATIVO",
                "statusNovo": "BLOQUEADO",
                "alteradoEm": datetime(2026, 1, 1, 12, 10, tzinfo=UTC).isoformat(),
            },
        )

        apto, motivo = verificar_apto_a_criar_campanha(conn, "usr-1")
        assert not apto
        assert "BLOQUEADO" in (motivo or "")

        # 4. Desbloqueio do usuário restaura aptidão
        consumir_usuario_status_alterado(
            conn,
            {
                "usuarioId": "usr-1",
                "statusAnterior": "BLOQUEADO",
                "statusNovo": "ATIVO",
                "alteradoEm": datetime(2026, 1, 1, 12, 15, tzinfo=UTC).isoformat(),
            },
        )

        apto, motivo = verificar_apto_a_criar_campanha(conn, "usr-1")
        assert apto
        assert motivo is None


def test_investidor_nao_cria_campanha_mesmo_ativo(tmp_path: Path) -> None:
    inicializar_banco(tmp_path)

    with closing(open_db("campanhas", tmp_path)) as conn:
        consumir_usuario_cadastrado(
            conn,
            {
                "usuarioId": "inv-1",
                "perfil": "INVESTIDOR",
                "cadastradoEm": datetime(2026, 1, 1, 12, 0, tzinfo=UTC).isoformat(),
            },
        )

        apto, motivo = verificar_apto_a_criar_campanha(conn, "inv-1")
        assert not apto
        assert "INVESTIDOR" in (motivo or "")
