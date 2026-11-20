"""Rotas HTTP da API de Notificações."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from notificacao.repository import (
    listar_notificacoes_usuario,
    marcar_notificacao_como_lida,
    obter_notificacao_por_id,
)
from shared.auth import segredo_do_ambiente, validar_token
from shared.db import open_db, transaction


class NotificacaoResponse(BaseModel):
    """Modelo de resposta para uma notificação."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    usuario_id: str = Field(alias="usuarioId")
    evento_origem_id: str = Field(alias="eventoOrigemId")
    tipo_evento: str = Field(alias="tipoEvento")
    titulo: str
    mensagem: str
    status_envio: str = Field(alias="statusEnvio")
    lida: bool
    criado_em: str | None = Field(default=None, alias="criadoEm")
    enviado_em: str | None = Field(default=None, alias="enviadoEm")


def extrair_usuario_autenticado(
    x_user_id: str | None,
    authorization: str | None,
) -> str:
    """Extrai o identificador do usuário a partir do header X-User-ID ou do token JWT."""
    if x_user_id and x_user_id.strip():
        return x_user_id.strip()

    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        try:
            segredo, _ = segredo_do_ambiente()
            claims = validar_token(token, segredo=segredo)
            return claims.sub
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de autenticação inválido ou expirado.",
            ) from exc

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais de autenticação não fornecidas.",
    )


def criar_notificacao_router(data_dir: str | Path = "data") -> APIRouter:
    """Cria roteador com endpoints de consulta e interação com notificações."""
    router = APIRouter()

    @router.get("/notificacoes", response_model=list[NotificacaoResponse])
    async def listar_minhas_notificacoes(
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> list[NotificacaoResponse]:
        """Retorna todas as notificações do usuário autenticado."""
        usuario_id = extrair_usuario_autenticado(x_user_id, authorization)

        with closing(open_db("notificacao", data_dir)) as conn:
            notificacoes = listar_notificacoes_usuario(conn, usuario_id)

        return [
            NotificacaoResponse(
                id=n.id,
                usuarioId=n.usuario_id,
                eventoOrigemId=n.evento_origem_id,
                tipoEvento=n.tipo_evento,
                titulo=n.titulo,
                mensagem=n.mensagem,
                statusEnvio=n.status_envio.value,
                lida=n.lida,
                criadoEm=n.criado_em.isoformat() if n.criado_em else None,
                enviadoEm=n.enviado_em.isoformat() if n.enviado_em else None,
            )
            for n in notificacoes
        ]

    @router.post("/notificacoes/{notificacao_id}/lida")
    async def marcar_como_lida(
        notificacao_id: str,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> dict[str, str | bool]:
        """Marca uma notificação como lida para o usuário autenticado."""
        usuario_id = extrair_usuario_autenticado(x_user_id, authorization)

        def operacao(conn: sqlite3.Connection) -> bool:
            existente = obter_notificacao_por_id(conn, notificacao_id)
            if existente is None or existente.usuario_id != usuario_id:
                return False
            return marcar_notificacao_como_lida(conn, notificacao_id, usuario_id)

        alterado = transaction(operacao, "notificacao", data_dir)
        if not alterado:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notificação não encontrada.",
            )

        return {"id": notificacao_id, "lida": True}

    return router
