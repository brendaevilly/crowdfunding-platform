"""Testes unitários do domínio do módulo Contas."""

from datetime import UTC, datetime

import pytest

from contracts.eventos import Perfil
from identidade.contas.dominio import Email, StatusUsuario, Usuario
from identidade.contas.seguranca import gerar_hash_senha, verificar_senha


def test_email_valido_e_normalizado() -> None:
    """E-mail válido deve ser aceito e normalizado em minúsculas."""
    email = Email("  Usuario.Teste@Exemplo.COM  ")
    assert email.valor == "usuario.teste@exemplo.com"
    assert str(email) == "usuario.teste@exemplo.com"


def test_email_invalido_dispara_erro() -> None:
    """E-mail malformatado deve ser rejeitado."""
    with pytest.raises(ValueError, match="E-mail inválido"):
        Email("invalido-sem-arroba")

    with pytest.raises(ValueError, match="E-mail inválido"):
        Email("@semusuario.com")

    with pytest.raises(ValueError, match="E-mail inválido"):
        Email("usuario@semdominio")


def test_hash_senha_scrypt() -> None:
    """Senha deve ser hasheada com scrypt e verificável."""
    senha = "senhaSuperSecreta123"
    hash_senha = gerar_hash_senha(senha)

    assert hash_senha.startswith("scrypt$")
    assert verificar_senha(senha, hash_senha) is True
    assert verificar_senha("senhaErrada", hash_senha) is False


def test_hash_senha_curta_rejeitada() -> None:
    """Senha menor que 6 caracteres deve ser rejeitada."""
    with pytest.raises(ValueError, match="mínimo 6 caracteres"):
        gerar_hash_senha("12345")


def test_ativacao_de_usuario_pendente() -> None:
    """Usuário com status PENDENTE pode ser ativado."""
    agora = datetime.now(UTC)
    usuario = Usuario(
        id="usr-1",
        nome="Fulano",
        email=Email("fulano@exemplo.com"),
        senha_hash=gerar_hash_senha("senha123"),
        perfil=Perfil.EMPREENDEDOR,
        status=StatusUsuario.PENDENTE,
        criado_em=agora,
        atualizado_em=agora,
    )

    ativo = usuario.ativar()
    assert ativo.status == StatusUsuario.ATIVO
    assert ativo.atualizado_em >= agora


def test_bloqueado_nao_pode_ser_ativado_diretamente() -> None:
    """Usuário bloqueado não pode ser ativado por confirmação simples."""
    agora = datetime.now(UTC)
    usuario = Usuario(
        id="usr-2",
        nome="Ciclano",
        email=Email("ciclano@exemplo.com"),
        senha_hash=gerar_hash_senha("senha123"),
        perfil=Perfil.INVESTIDOR,
        status=StatusUsuario.BLOQUEADO,
        criado_em=agora,
        atualizado_em=agora,
    )

    with pytest.raises(ValueError, match="Usuário bloqueado não pode ser ativado"):
        usuario.ativar()
