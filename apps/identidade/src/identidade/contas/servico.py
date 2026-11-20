"""Casos de uso e orquestração do bounded context Contas."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from contracts.eventos import (
    Perfil,
    UsuarioCadastrado,
    UsuarioStatusAlterado,
)
from contracts.eventos import (
    StatusUsuario as StatusUsuarioContrato,
)
from contracts.topicos import USUARIO_CADASTRADO, USUARIO_STATUS_ALTERADO
from identidade.contas import repositorio
from identidade.contas.dominio import Email, StatusUsuario, Usuario
from identidade.contas.seguranca import gerar_hash_senha, verificar_senha
from shared.auth import (
    emitir_token,
    expiracao_do_ambiente,
    segredo_do_ambiente,
)
from shared.correlation import get_correlation_id
from shared.db import open_db, transaction
from shared.outbox import OutboxEvent, add


class EmailJaCadastradoErro(Exception):
    """Lançado quando o e-mail já existe no sistema."""


class UsuarioNaoEncontradoErro(Exception):
    """Lançado quando o usuário não é encontrado."""


class CredenciaisInvalidasErro(Exception):
    """Lançado quando as credenciais não permitem autenticação."""


class PermissaoNegadaErro(Exception):
    """Lançado quando o usuário não possui permissão administrativa."""


def cadastrar_usuario(
    *,
    nome: str,
    email_str: str,
    senha_plana: str,
    perfil: Perfil,
    data_dir: str | Path = "data",
    auto_ativar: bool = False,
) -> Usuario:
    """Cadastra um usuário e registra UsuarioCadastrado na outbox."""

    email = Email(email_str)
    senha_hash = gerar_hash_senha(senha_plana)
    agora = datetime.now(UTC)
    usuario_id = str(uuid.uuid4())

    status_inicial = StatusUsuario.ATIVO if auto_ativar else StatusUsuario.PENDENTE

    usuario = Usuario(
        id=usuario_id,
        nome=nome.strip(),
        email=email,
        senha_hash=senha_hash,
        perfil=perfil,
        status=status_inicial,
        criado_em=agora,
        atualizado_em=agora,
    )

    evento_contrato = UsuarioCadastrado(
        usuario_id=usuario_id,
        perfil=perfil,
        cadastrado_em=agora,
    )

    payload_evento = evento_contrato.model_dump(
        by_alias=True,
        mode="json",
    )

    correlation_id = get_correlation_id() or str(uuid.uuid4())

    def operacao(conn: sqlite3.Connection) -> Usuario:
        try:
            repositorio.salvar_usuario(conn, usuario)

        except sqlite3.IntegrityError as exc:
            if "contas_usuarios.email" in str(exc) or "UNIQUE" in str(exc).upper():
                raise EmailJaCadastradoErro(f"E-mail já cadastrado: {email.valor}") from exc

            raise

        add(
            conn,
            OutboxEvent(
                agregado_id=usuario_id,
                tipo_evento=USUARIO_CADASTRADO,
                payload=payload_evento,
                correlation_id=correlation_id,
            ),
        )

        return usuario

    return transaction(operacao, "identidade", data_dir)


def ativar_usuario(
    usuario_id: str,
    data_dir: str | Path = "data",
) -> Usuario:
    """Ativa um usuário que estava com status PENDENTE."""

    def operacao(conn: sqlite3.Connection) -> Usuario:
        usuario = repositorio.buscar_usuario_por_id(
            conn,
            usuario_id,
        )

        if usuario is None:
            raise UsuarioNaoEncontradoErro(f"Usuário não encontrado: {usuario_id}")

        usuario_ativo = usuario.ativar()

        repositorio.atualizar_status_usuario(
            conn,
            usuario_id,
            usuario_ativo.status,
            usuario_ativo.atualizado_em,
        )

        return usuario_ativo

    return transaction(operacao, "identidade", data_dir)


def autenticar_usuario(
    *,
    email_str: str,
    senha_plana: str,
    data_dir: str | Path = "data",
) -> str:
    """Autentica um usuário ativo e emite um JWT compatível com o Gateway."""

    with closing(open_db("identidade", data_dir)) as conn:
        usuario = repositorio.buscar_usuario_por_email(
            conn,
            email_str,
        )

    mensagem_erro = "E-mail ou senha inválidos"

    if usuario is None:
        raise CredenciaisInvalidasErro(mensagem_erro)

    if not verificar_senha(
        senha_plana,
        usuario.senha_hash,
    ):
        raise CredenciaisInvalidasErro(mensagem_erro)

    if usuario.status == StatusUsuario.BLOQUEADO:
        raise CredenciaisInvalidasErro("Usuário bloqueado pelo administrador")

    if usuario.status == StatusUsuario.PENDENTE:
        ativar_usuario(usuario.id, data_dir=data_dir)
        usuario = usuario.ativar()

    if usuario.status != StatusUsuario.ATIVO:
        raise CredenciaisInvalidasErro(mensagem_erro)

    segredo, _ = segredo_do_ambiente()

    return emitir_token(
        sub=usuario.id,
        perfil=usuario.perfil.value,
        segredo=segredo,
        expira_em_segundos=expiracao_do_ambiente(),
    )


def consultar_usuario_autenticado(
    usuario_id: str,
    data_dir: str | Path = "data",
) -> Usuario:
    """Consulta o usuário autenticado e exige uma conta ativa."""

    with closing(open_db("identidade", data_dir)) as conn:
        usuario = repositorio.buscar_usuario_por_id(
            conn,
            usuario_id,
        )

    if usuario is None or usuario.status != StatusUsuario.ATIVO:
        raise CredenciaisInvalidasErro("Usuário inexistente ou inativo")

    return usuario


def alterar_status_usuario_admin(
    *,
    administrador_id: str,
    usuario_id: str,
    bloquear: bool,
    motivo: str | None = None,
    data_dir: str | Path = "data",
) -> Usuario:
    """Altera o status de um usuário com autorização administrativa.

    A atualização do banco e a inclusão do evento na outbox
    acontecem dentro da mesma transação.
    """

    def operacao(conn: sqlite3.Connection) -> Usuario:
        administrador = repositorio.buscar_usuario_por_id(
            conn,
            administrador_id,
        )

        # Somente um ADMIN ativo pode realizar a operação.
        if (
            administrador is None
            or administrador.perfil != Perfil.ADMIN
            or administrador.status != StatusUsuario.ATIVO
        ):
            raise PermissaoNegadaErro("Somente administradores ativos podem alterar usuários")

        # Impede o administrador de bloquear a própria conta.
        if administrador_id == usuario_id:
            raise PermissaoNegadaErro("O administrador não pode alterar o próprio status")

        usuario = repositorio.buscar_usuario_por_id(
            conn,
            usuario_id,
        )

        if usuario is None:
            raise UsuarioNaoEncontradoErro(f"Usuário não encontrado: {usuario_id}")

        # Executa a transição de estado no domínio.
        usuario_atualizado = usuario.bloquear() if bloquear else usuario.desbloquear()

        # Atualiza o status no SQLite.
        repositorio.atualizar_status_usuario(
            conn,
            usuario_id,
            usuario_atualizado.status,
            usuario_atualizado.atualizado_em,
        )

        # Monta o contrato do evento.
        evento = UsuarioStatusAlterado(
            usuario_id=usuario_id,
            status_anterior=StatusUsuarioContrato(usuario.status.value),
            status_novo=StatusUsuarioContrato(usuario_atualizado.status.value),
            motivo=motivo,
            alterado_em=usuario_atualizado.atualizado_em,
        )

        # Registra o evento na outbox.
        add(
            conn,
            OutboxEvent(
                agregado_id=usuario_id,
                tipo_evento=USUARIO_STATUS_ALTERADO,
                payload=evento.model_dump(
                    by_alias=True,
                    mode="json",
                ),
                correlation_id=(get_correlation_id() or str(uuid.uuid4())),
            ),
        )

        return usuario_atualizado

    return transaction(operacao, "identidade", data_dir)


def bloquear_usuario(
    *,
    administrador_id: str,
    usuario_id: str,
    motivo: str | None = None,
    data_dir: str | Path = "data",
) -> Usuario:
    """Bloqueia um usuário mediante autorização administrativa."""

    return alterar_status_usuario_admin(
        administrador_id=administrador_id,
        usuario_id=usuario_id,
        bloquear=True,
        motivo=motivo,
        data_dir=data_dir,
    )


def desbloquear_usuario(
    *,
    administrador_id: str,
    usuario_id: str,
    motivo: str | None = None,
    data_dir: str | Path = "data",
) -> Usuario:
    """Desbloqueia um usuário mediante autorização administrativa."""

    return alterar_status_usuario_admin(
        administrador_id=administrador_id,
        usuario_id=usuario_id,
        bloquear=False,
        motivo=motivo,
        data_dir=data_dir,
    )
