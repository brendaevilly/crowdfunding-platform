"""Rotas HTTP do bounded context Contas."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from contracts.eventos import Perfil
from identidade.contas.dominio import Usuario
from identidade.contas.servico import (
    EmailJaCadastradoErro,
    UsuarioNaoEncontradoErro,
    ativar_usuario,
    cadastrar_usuario,
)


class CadastrarUsuarioRequest(BaseModel):
    """Payload para criação de usuário."""

    nome: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    senha: str = Field(min_length=6, max_length=128)
    perfil: Perfil


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
    return UsuarioResponse(
        id=usuario.id,
        nome=usuario.nome,
        email=usuario.email.valor,
        perfil=usuario.perfil,
        status=usuario.status.value,
        criadoEm=usuario.criado_em.isoformat(),
    )


def criar_contas_router(data_dir: str | Path = "data") -> APIRouter:
    """Cria o router com as rotas de usuários."""
    router = APIRouter(tags=["contas"])

    @router.post(
        "/usuarios",
        response_model=UsuarioResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def post_cadastrar_usuario(body: CadastrarUsuarioRequest) -> UsuarioResponse:
        auto_ativar = os.getenv("IDENTIDADE_AUTO_ATIVAR", "false").lower() in (
            "true",
            "1",
            "yes",
        )
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
    def post_ativar_usuario(usuario_id: str) -> UsuarioResponse:
        try:
            usuario = ativar_usuario(usuario_id, data_dir=data_dir)
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

    return router
