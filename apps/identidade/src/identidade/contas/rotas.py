"""Rotas HTTP do bounded context Contas."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from contracts.eventos import Perfil
from identidade.contas.dominio import Usuario
from identidade.contas.servico import (
    CredenciaisInvalidasErro,
    EmailJaCadastradoErro,
    PermissaoNegadaErro,
    UsuarioNaoEncontradoErro,
    ativar_usuario,
    autenticar_usuario,
    bloquear_usuario,
    cadastrar_usuario,
    consultar_usuario_autenticado,
    desbloquear_usuario,
)
from shared.auth import TokenInvalido, segredo_do_ambiente, validar_token


class CadastrarUsuarioRequest(BaseModel):
    """Payload para criação de usuário."""

    nome: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    senha: str = Field(min_length=6, max_length=128)
    perfil: Perfil


class LoginRequest(BaseModel):
    """Credenciais utilizadas na autenticação."""

    email: str = Field(min_length=3, max_length=255)
    senha: str = Field(min_length=1)


class LoginResponse(BaseModel):
    """Token JWT emitido após autenticação."""

    access_token: str
    token_type: str = "bearer"


class AlterarStatusRequest(BaseModel):
    """Justificativa opcional para bloqueio ou desbloqueio."""

    motivo: str | None = Field(
        default=None,
        max_length=500,
    )


class UsuarioResponse(BaseModel):
    """Representação pública de um usuário cadastrado."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    nome: str
    email: str
    perfil: Perfil
    status: str
    criadoEm: str


def _usuario_para_response(usuario: Usuario) -> UsuarioResponse:
    """Converte o usuário para resposta pública, sem expor a senha."""

    return UsuarioResponse(
        id=usuario.id,
        nome=usuario.nome,
        email=usuario.email.valor,
        perfil=usuario.perfil,
        status=usuario.status.value,
        criadoEm=usuario.criado_em.isoformat(),
    )


def _autenticar_requisicao(
    request: Request,
    data_dir: str | Path,
) -> Usuario:
    """Valida JWT, status e perfil atual do usuário no banco."""

    authorization = request.headers.get("authorization", "")
    esquema, _, token = authorization.partition(" ")

    if esquema.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticação ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )

    segredo, _ = segredo_do_ambiente()

    try:
        claims = validar_token(
            token.strip(),
            segredo=segredo,
        )

        usuario = consultar_usuario_autenticado(
            claims.sub,
            data_dir=data_dir,
        )

        if claims.perfil != usuario.perfil.value:
            raise CredenciaisInvalidasErro("Perfil do token não corresponde ao usuário")

    except (TokenInvalido, CredenciaisInvalidasErro) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou usuário inativo",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return usuario


def _exigir_administrador(
    request: Request,
    data_dir: str | Path,
) -> Usuario:
    """Exige que o solicitante seja um administrador ativo."""

    usuario = _autenticar_requisicao(
        request,
        data_dir,
    )

    if usuario.perfil != Perfil.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso permitido somente a administradores",
        )

    return usuario


def criar_contas_router(data_dir: str | Path = "data") -> APIRouter:
    """Cria o router com as rotas de usuários e autenticação."""

    router = APIRouter(tags=["contas"])

    # ---------------------------------------------------------------
    # Cadastro público de usuários
    # ---------------------------------------------------------------

    @router.post(
        "/usuarios",
        response_model=UsuarioResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def post_cadastrar_usuario(
        body: CadastrarUsuarioRequest,
    ) -> UsuarioResponse:
        """Cadastra usuários, impedindo a criação pública de ADMIN."""

        if body.perfil == Perfil.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="O perfil ADMIN não pode ser criado pelo cadastro público",
            )

        auto_ativar = os.getenv(
            "IDENTIDADE_AUTO_ATIVAR",
            "false",
        ).lower() in ("true", "1", "yes")

        try:
            usuario = cadastrar_usuario(
                nome=body.nome,
                email_str=body.email,
                senha_plana=body.senha,
                perfil=body.perfil,
                data_dir=data_dir,
                auto_ativar=auto_ativar,
            )

        except EmailJaCadastradoErro as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        return _usuario_para_response(usuario)

    # ---------------------------------------------------------------
    # Login JWT
    # ---------------------------------------------------------------

    @router.post(
        "/auth/login",
        response_model=LoginResponse,
        status_code=status.HTTP_200_OK,
    )
    @router.post(
        "/login",
        response_model=LoginResponse,
        status_code=status.HTTP_200_OK,
    )
    def post_login(
        body: LoginRequest,
    ) -> LoginResponse:
        """Autentica um usuário ativo e retorna um JWT."""

        try:
            token = autenticar_usuario(
                email_str=body.email,
                senha_plana=body.senha,
                data_dir=data_dir,
            )

        except CredenciaisInvalidasErro as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="E-mail ou senha inválidos",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        return LoginResponse(
            access_token=token,
            token_type="bearer",
        )

    # ---------------------------------------------------------------
    # Consultar perfil do usuário autenticado
    # ---------------------------------------------------------------

    @router.get(
        "/usuarios/me",
        response_model=UsuarioResponse,
        status_code=status.HTTP_200_OK,
    )
    def get_usuario_me(
        request: Request,
    ) -> UsuarioResponse:
        """Retorna os dados do usuário autenticado pelo JWT."""

        usuario = _autenticar_requisicao(
            request,
            data_dir,
        )

        return _usuario_para_response(usuario)

    # ---------------------------------------------------------------
    # Ativação e confirmação de usuários
    # ---------------------------------------------------------------

    @router.post(
        "/usuarios/{usuario_id}/ativar",
        response_model=UsuarioResponse,
        status_code=status.HTTP_200_OK,
    )
    @router.post(
        "/usuarios/{usuario_id}/confirmar",
        response_model=UsuarioResponse,
        status_code=status.HTTP_200_OK,
    )
    def post_ativar_usuario(
        usuario_id: str,
    ) -> UsuarioResponse:
        """Ativa um usuário que estava pendente."""

        try:
            usuario = ativar_usuario(
                usuario_id,
                data_dir=data_dir,
            )

        except UsuarioNaoEncontradoErro as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        return _usuario_para_response(usuario)

    # ---------------------------------------------------------------
    # Bloqueio administrativo de usuários
    # ---------------------------------------------------------------

    @router.post(
        "/usuarios/{usuario_id}/bloquear",
        response_model=UsuarioResponse,
        status_code=status.HTTP_200_OK,
    )
    def post_bloquear_usuario(
        usuario_id: str,
        request: Request,
        body: AlterarStatusRequest | None = None,
    ) -> UsuarioResponse:
        """Bloqueia um usuário mediante autenticação ADMIN."""

        administrador = _exigir_administrador(
            request,
            data_dir,
        )

        try:
            usuario = bloquear_usuario(
                administrador_id=administrador.id,
                usuario_id=usuario_id,
                motivo=body.motivo if body is not None else None,
                data_dir=data_dir,
            )

        except PermissaoNegadaErro as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc

        except UsuarioNaoEncontradoErro as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        return _usuario_para_response(usuario)

    # ---------------------------------------------------------------
    # Desbloqueio administrativo de usuários
    # ---------------------------------------------------------------

    @router.post(
        "/usuarios/{usuario_id}/desbloquear",
        response_model=UsuarioResponse,
        status_code=status.HTTP_200_OK,
    )
    def post_desbloquear_usuario(
        usuario_id: str,
        request: Request,
        body: AlterarStatusRequest | None = None,
    ) -> UsuarioResponse:
        """Desbloqueia um usuário mediante autenticação ADMIN."""

        administrador = _exigir_administrador(
            request,
            data_dir,
        )

        try:
            usuario = desbloquear_usuario(
                administrador_id=administrador.id,
                usuario_id=usuario_id,
                motivo=body.motivo if body is not None else None,
                data_dir=data_dir,
            )

        except PermissaoNegadaErro as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc

        except UsuarioNaoEncontradoErro as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        return _usuario_para_response(usuario)

    return router
