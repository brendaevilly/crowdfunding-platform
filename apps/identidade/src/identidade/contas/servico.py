"""Casos de uso e orquestração do bounded context Contas."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from contracts.eventos import Perfil, UsuarioCadastrado
from contracts.topicos import USUARIO_CADASTRADO
from identidade.contas import repositorio
from identidade.contas.dominio import Email, StatusUsuario, Usuario
from identidade.contas.seguranca import gerar_hash_senha
from shared.correlation import get_correlation_id
from shared.db import transaction
from shared.outbox import OutboxEvent, add


class EmailJaCadastradoErro(Exception):
    """Lançado quando o e-mail já existe no sistema."""


class UsuarioNaoEncontradoErro(Exception):
    """Lançado quando o usuário não é encontrado."""


def cadastrar_usuario(
    *,
    nome: str,
    email_str: str,
    senha_plana: str,
    perfil: Perfil,
    data_dir: str | Path = "data",
    auto_ativar: bool = False,
) -> Usuario:
    """Cadastra um novo usuário e registra o evento UsuarioCadastrado na outbox."""
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
    payload_evento = evento_contrato.model_dump(by_alias=True, mode="json")
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
        usuario = repositorio.buscar_usuario_por_id(conn, usuario_id)
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
