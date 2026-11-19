"""Testes da criação do administrador inicial."""

from contextlib import closing
from pathlib import Path

import pytest
from seed_admin import criar_admin

from contracts.eventos import Perfil
from identidade.contas import repositorio
from identidade.contas.dominio import StatusUsuario
from identidade.contas.seguranca import verificar_senha
from shared.db import open_db


def test_seed_cria_admin_ativo(tmp_path: Path) -> None:
    """Verifica se o seed cria um administrador ativo com senha protegida."""
    administrador, criado = criar_admin(
        nome="Administrador",
        email_str="admin@exemplo.com",
        senha_plana="SenhaSegura123!",
        data_dir=tmp_path,
    )

    assert criado is True
    assert administrador.perfil == Perfil.ADMIN
    assert administrador.status == StatusUsuario.ATIVO
    assert administrador.senha_hash != "SenhaSegura123!"
    assert verificar_senha("SenhaSegura123!", administrador.senha_hash)

    with closing(open_db("identidade", tmp_path)) as conn:
        salvo = repositorio.buscar_usuario_por_email(
            conn,
            "admin@exemplo.com",
        )

    assert salvo is not None
    assert salvo.id == administrador.id
    assert salvo.perfil == Perfil.ADMIN
    assert salvo.status == StatusUsuario.ATIVO


def test_seed_nao_duplica_admin(tmp_path: Path) -> None:
    """Verifica se executar o seed novamente não duplica o administrador."""
    primeiro, criado_primeiro = criar_admin(
        nome="Administrador",
        email_str="admin@exemplo.com",
        senha_plana="SenhaSegura123!",
        data_dir=tmp_path,
    )

    segundo, criado_segundo = criar_admin(
        nome="Administrador",
        email_str="admin@exemplo.com",
        senha_plana="SenhaSegura123!",
        data_dir=tmp_path,
    )

    assert criado_primeiro is True
    assert criado_segundo is False
    assert primeiro.id == segundo.id
    assert primeiro.email.valor == segundo.email.valor


def test_seed_rejeita_senha_curta(tmp_path: Path) -> None:
    """Verifica se o seed rejeita senhas com menos de 12 caracteres."""
    with pytest.raises(ValueError, match="12 caracteres"):
        criar_admin(
            nome="Administrador",
            email_str="admin@exemplo.com",
            senha_plana="123456",
            data_dir=tmp_path,
        )
