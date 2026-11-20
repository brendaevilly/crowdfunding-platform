"""Rotas HTTP da API de Campanhas."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from campanhas.domain import (
    Campanha,
    ConcorrenciaOtimistaError,
    TransicaoInvalidaError,
)
from campanhas.domain import (
    StatusCampanha as DomainStatus,
)
from campanhas.repository import (
    atualizar_campanha_rascunho,
    obter_campanha_por_id,
    salvar_nova_campanha,
)
from campanhas.usuarios_cache import verificar_apto_a_criar_campanha
from contracts.campanhas_api import CampanhaStatusResponse
from contracts.campanhas_api import StatusCampanha as ContractStatus
from shared.db import transaction


class CriarCampanhaRequest(BaseModel):
    """Payload para criação de nova campanha."""

    model_config = ConfigDict(populate_by_name=True)

    titulo: str = Field(min_length=1)
    descricao: str = Field(min_length=1)
    meta: int = Field(gt=0, description="Meta em centavos")
    prazo_inicio: datetime = Field(alias="prazoInicio")
    prazo_fim: datetime = Field(alias="prazoFim")
    empreendedor_id: str | None = Field(default=None, alias="empreendedorId")


class AtualizarCampanhaRequest(BaseModel):
    """Payload para atualização de campanha em rascunho."""

    model_config = ConfigDict(populate_by_name=True)

    titulo: str = Field(min_length=1)
    descricao: str = Field(min_length=1)
    meta: int = Field(gt=0, description="Meta em centavos")
    prazo_inicio: datetime = Field(alias="prazoInicio")
    prazo_fim: datetime = Field(alias="prazoFim")
    versao: int | None = Field(
        default=None, description="Versão esperada para concorrência otimista"
    )


def _campanha_to_dict(c: Campanha) -> dict[str, object]:
    return {
        "id": c.id,
        "empreendedorId": c.empreendedor_id,
        "titulo": c.titulo,
        "descricao": c.descricao,
        "meta": c.meta.centavos,
        "prazoInicio": c.prazo.inicio.isoformat(),
        "prazoFim": c.prazo.fim.isoformat(),
        "status": c.status.value,
        "valorArrecadado": c.valor_arrecadado,
        "motivoReprovacao": c.motivo_reprovacao,
        "versao": c.versao,
        "criadoEm": c.criado_em.isoformat(),
        "atualizadoEm": c.atualizado_em.isoformat(),
    }


def criar_campanhas_router(data_dir: str | Path = "data") -> APIRouter:
    """Cria roteador com operações do agregado Campanha."""
    router = APIRouter()

    @router.post("/campanhas", status_code=status.HTTP_201_CREATED)
    async def criar_campanha(
        dados: CriarCampanhaRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
        x_user_perfil: str | None = Header(default=None, alias="X-User-Perfil"),
    ) -> JSONResponse:
        # Define o id do empreendedor priorizando o cabeçalho seguro do gateway
        empreendedor_id = x_user_id or dados.empreendedor_id
        if not empreendedor_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Identificação do empreendedor é obrigatória.",
            )

        if x_user_id and dados.empreendedor_id and x_user_id != dados.empreendedor_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuário autenticado difere do empreendedor informado.",
            )

        if x_user_perfil is not None and x_user_perfil != "EMPREENDEDOR":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas usuários com perfil EMPREENDEDOR podem criar campanhas.",
            )

        # Validação do Prazo
        if dados.prazo_fim <= dados.prazo_inicio:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="O prazo final deve ser posterior ao prazo inicial.",
            )

        def operacao(conn: sqlite3.Connection) -> Campanha:
            apto, motivo = verificar_apto_a_criar_campanha(conn, empreendedor_id)
            if not apto:
                raise PermissionError(motivo)

            campanha = Campanha.criar(
                empreendedor_id=empreendedor_id,
                titulo=dados.titulo,
                descricao=dados.descricao,
                meta=dados.meta,
                prazo_inicio=dados.prazo_inicio,
                prazo_fim=dados.prazo_fim,
            )
            salvar_nova_campanha(conn, campanha)
            return campanha

        try:
            campanha_criada = transaction(operacao, "campanhas", data_dir)
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=_campanha_to_dict(campanha_criada),
        )

    @router.get("/campanhas/{campanha_id}")
    async def obter_campanha(campanha_id: str) -> JSONResponse:
        def operacao(conn: sqlite3.Connection) -> Campanha | None:
            return obter_campanha_por_id(conn, campanha_id)

        campanha = transaction(operacao, "campanhas", data_dir)
        if campanha is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Campanha '{campanha_id}' não encontrada.",
            )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=_campanha_to_dict(campanha),
        )

    @router.put("/campanhas/{campanha_id}")
    async def atualizar_campanha(
        campanha_id: str,
        dados: AtualizarCampanhaRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> JSONResponse:
        if dados.prazo_fim <= dados.prazo_inicio:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="O prazo final deve ser posterior ao prazo inicial.",
            )

        def operacao(conn: sqlite3.Connection) -> Campanha:
            campanha = obter_campanha_por_id(conn, campanha_id)
            if campanha is None:
                raise KeyError(f"Campanha '{campanha_id}' não encontrada.")

            if x_user_id and x_user_id != campanha.empreendedor_id:
                raise PermissionError("Apenas o empreendedor dono da campanha pode editá-la.")

            versao_alvo = dados.versao if dados.versao is not None else campanha.versao

            campanha.editar(
                titulo=dados.titulo,
                descricao=dados.descricao,
                meta=dados.meta,
                prazo_inicio=dados.prazo_inicio,
                prazo_fim=dados.prazo_fim,
                versao_esperada=versao_alvo,
            )

            atualizar_campanha_rascunho(conn, campanha, versao_alvo)
            return campanha

        try:
            campanha_atualizada = transaction(operacao, "campanhas", data_dir)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc
        except TransicaoInvalidaError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ConcorrenciaOtimistaError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=_campanha_to_dict(campanha_atualizada),
        )

    @router.get("/campanhas/{campanha_id}/status")
    async def obter_status_campanha(campanha_id: str) -> CampanhaStatusResponse:
        """Endpoint síncrono para verificação de status (usado pelo microsserviço Aportes)."""

        def operacao(conn: sqlite3.Connection) -> Campanha | None:
            return obter_campanha_por_id(conn, campanha_id)

        campanha = transaction(operacao, "campanhas", data_dir)
        if campanha is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Campanha '{campanha_id}' não encontrada.",
            )

        # Mapeamento para o contrato com Aportes
        status_contrato: ContractStatus
        if campanha.status == DomainStatus.PUBLICADA:
            status_contrato = ContractStatus.PUBLICADA
        elif campanha.status == DomainStatus.ENCERRADA:
            status_contrato = ContractStatus.ENCERRADA
        elif campanha.status == DomainStatus.CANCELADA:
            status_contrato = ContractStatus.CANCELADA
        else:
            status_contrato = ContractStatus.RASCUNHO

        return CampanhaStatusResponse(
            campanha_id=campanha.id,
            status=status_contrato,
        )

    return router
