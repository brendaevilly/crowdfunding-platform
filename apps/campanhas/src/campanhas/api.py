"""Rotas HTTP da API de Gestão de Campanhas."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query, status
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
    atualizar_campanha as repo_atualizar_campanha,
)
from campanhas.repository import (
    atualizar_campanha_rascunho,
    executar_leitura,
    listar_campanhas,
    obter_campanha_por_id,
    salvar_nova_campanha,
)
from campanhas.usuarios_cache import verificar_apto_a_criar_campanha
from contracts.campanhas_api import CampanhaStatusResponse
from contracts.campanhas_api import StatusCampanha as ContractStatus
from contracts.eventos import CampanhaPublicada
from contracts.topicos import CAMPANHA_PUBLICADA
from shared.db import transaction
from shared.outbox import OutboxEvent, add


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


class ReprovarCampanhaRequest(BaseModel):
    """Payload para reprovação de campanha."""

    model_config = ConfigDict(populate_by_name=True)

    motivo: str = Field(min_length=1, description="Motivo detalhado da reprovação")


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
        "metaAtingida": c.meta_atingida,
        "meta_atingida": c.meta_atingida,
        "motivoReprovacao": c.motivo_reprovacao,
        "versao": c.versao,
        "criadoEm": c.criado_em.isoformat(),
        "atualizadoEm": c.atualizado_em.isoformat(),
    }


def criar_campanhas_router(data_dir: str | Path = "data") -> APIRouter:
    """Cria roteador com operações do agregado Campanha e fluxo de moderação."""
    router = APIRouter()

    @router.post("/campanhas", status_code=status.HTTP_201_CREATED)
    async def criar_campanha(
        dados: CriarCampanhaRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
        x_user_perfil: str | None = Header(default=None, alias="X-User-Perfil"),
    ) -> JSONResponse:
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

    @router.get("/campanhas")
    async def listar_campanhas_endpoint(
        status_filtro: str | None = Query(default=None, alias="status"),
        limite: int = Query(default=20, ge=1, le=100, alias="limite"),
        offset: int = Query(default=0, ge=0, alias="offset"),
        limit: int | None = Query(default=None, alias="limit"),
        ativas: bool | None = Query(default=None, alias="ativas"),
    ) -> JSONResponse:
        status_enum: DomainStatus | None = None
        tamanho_limite = limit if limit is not None else limite

        if status_filtro:
            if status_filtro.upper() in ("ATIVA", "ATIVAS", "PUBLICADA", "PUBLICADAS"):
                status_enum = DomainStatus.PUBLICADA
            else:
                try:
                    status_enum = DomainStatus(status_filtro)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Status '{status_filtro}' inválido.",
                    ) from exc
        elif ativas is True:
            status_enum = DomainStatus.PUBLICADA

        def operacao(conn: sqlite3.Connection) -> list[Campanha]:
            return listar_campanhas(
                conn,
                status=status_enum,
                limite=tamanho_limite,
                offset=offset,
            )

        # Listagem pública utiliza conexão de leitura separada (simulando réplica)
        campanhas = executar_leitura(operacao, data_dir)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=[_campanha_to_dict(c) for c in campanhas],
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
    async def atualizar_campanha_endpoint(
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
        except (TransicaoInvalidaError, ConcorrenciaOtimistaError) as exc:
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

    @router.post("/campanhas/{campanha_id}/submeter")
    async def submeter_campanha(
        campanha_id: str,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> JSONResponse:
        def operacao(conn: sqlite3.Connection) -> Campanha:
            campanha = obter_campanha_por_id(conn, campanha_id)
            if campanha is None:
                raise KeyError(f"Campanha '{campanha_id}' não encontrada.")

            if x_user_id and x_user_id != campanha.empreendedor_id:
                raise PermissionError("Apenas o empreendedor dono da campanha pode submetê-la.")

            versao_anterior = campanha.versao
            campanha.submeter()
            repo_atualizar_campanha(conn, campanha, versao_anterior)
            return campanha

        try:
            campanha_submetida = transaction(operacao, "campanhas", data_dir)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except (TransicaoInvalidaError, ConcorrenciaOtimistaError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=_campanha_to_dict(campanha_submetida),
        )

    @router.post("/campanhas/{campanha_id}/aprovar")
    async def aprovar_campanha(
        campanha_id: str,
        x_user_perfil: str | None = Header(default=None, alias="X-User-Perfil"),
        x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    ) -> JSONResponse:
        if x_user_perfil != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acesso restrito a administradores.",
            )

        def operacao(conn: sqlite3.Connection) -> Campanha:
            campanha = obter_campanha_por_id(conn, campanha_id)
            if campanha is None:
                raise KeyError(f"Campanha '{campanha_id}' não encontrada.")

            versao_anterior = campanha.versao
            campanha.aprovar()
            repo_atualizar_campanha(conn, campanha, versao_anterior)

            evento = CampanhaPublicada(
                campanha_id=campanha.id,
                empreendedor_id=campanha.empreendedor_id,
                meta=campanha.meta.centavos,
                prazo_fim=campanha.prazo.fim,
            )
            add(
                conn,
                OutboxEvent(
                    agregado_id=campanha.id,
                    tipo_evento=CAMPANHA_PUBLICADA,
                    payload=evento.model_dump(by_alias=True, mode="json"),
                    correlation_id=x_correlation_id or str(uuid4()),
                ),
            )
            return campanha

        try:
            campanha_aprovada = transaction(operacao, "campanhas", data_dir)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (TransicaoInvalidaError, ConcorrenciaOtimistaError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=_campanha_to_dict(campanha_aprovada),
        )

    @router.post("/campanhas/{campanha_id}/reprovar")
    async def reprovar_campanha(
        campanha_id: str,
        dados: ReprovarCampanhaRequest,
        x_user_perfil: str | None = Header(default=None, alias="X-User-Perfil"),
    ) -> JSONResponse:
        if x_user_perfil != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acesso restrito a administradores.",
            )

        motivo_limpo = dados.motivo.strip()
        if not motivo_limpo:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="O motivo da reprovação é obrigatório.",
            )

        def operacao(conn: sqlite3.Connection) -> Campanha:
            campanha = obter_campanha_por_id(conn, campanha_id)
            if campanha is None:
                raise KeyError(f"Campanha '{campanha_id}' não encontrada.")

            versao_anterior = campanha.versao
            campanha.reprovar(motivo_limpo)
            repo_atualizar_campanha(conn, campanha, versao_anterior)
            return campanha

        try:
            campanha_reprovada = transaction(operacao, "campanhas", data_dir)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (TransicaoInvalidaError, ConcorrenciaOtimistaError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=_campanha_to_dict(campanha_reprovada),
        )

    @router.get("/campanhas/{campanha_id}/status")
    async def obter_status_campanha(campanha_id: str) -> CampanhaStatusResponse:
        """Endpoint síncrono para verificação de status (usado pelo microsserviço Aportes).

        A decisão de aceitar aporte é sempre feita na conexão de escrita (primária).
        Regra 2: ativa só se status=ATIVA (PUBLICADA) e dentro do prazo.
        """

        def operacao(conn: sqlite3.Connection) -> Campanha | None:
            return obter_campanha_por_id(conn, campanha_id)

        # Decisão de aceitar aporte sempre na conexão de escrita (primária)
        campanha = transaction(operacao, "campanhas", data_dir)
        if campanha is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Campanha '{campanha_id}' não encontrada.",
            )

        agora = datetime.now(UTC)
        status_contrato: ContractStatus

        if campanha.status == DomainStatus.PUBLICADA:
            # Regra 2: se estiver fora do prazo, responde ENCERRADA mesmo se o status for PUBLICADA
            if agora > campanha.prazo.fim:
                status_contrato = ContractStatus.ENCERRADA
            else:
                status_contrato = ContractStatus.PUBLICADA
        elif campanha.status in (DomainStatus.ENCERRADA,):
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
