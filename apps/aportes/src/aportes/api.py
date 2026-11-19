"""Endpoints HTTP para criação, histórico e resumo de aportes."""

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from aportes.cliente_campanhas import (
    CampanhaIndisponivelError,
    ClienteCampanhas,
)
from aportes.domain import Valor
from aportes.historico import (
    HistoricoPaginado,
    ResumoCampanha,
    listar_aportes_investidor,
    obter_resumo_campanha,
)
from aportes.politica_limite_aporte import validar_limite_aporte
from aportes.processamento import (
    ChaveIdempotenciaConflitante,
    confirmar_aporte,
    consultar_resultado_anterior,
    rejeitar_aporte,
)
from aportes.status_investidor import investidor_esta_bloqueado
from shared.auth import (
    TokenInvalido,
    segredo_do_ambiente,
    validar_token,
)

router = APIRouter()


class CriarAporteRequest(BaseModel):
    """Dados necessários para solicitar um aporte."""

    model_config = ConfigDict(populate_by_name=True)

    campanha_id: str = Field(alias="campanhaId", min_length=1)
    investidor_id: str = Field(alias="investidorId", min_length=1)
    valor: int = Field(gt=0, strict=True)


def criar_router(
    *,
    cliente_campanhas: ClienteCampanhas | None = None,
    data_dir: str | Path = "data",
) -> APIRouter:
    """Cria as rotas de Aportes com dependências configuráveis."""

    api = APIRouter()
    cliente = cliente_campanhas if cliente_campanhas is not None else ClienteCampanhas()

    # ---------------------------------------------------------
    # POST /aportes
    # ---------------------------------------------------------

    @api.post("/aportes", status_code=201)
    async def criar_aporte(
        dados: CriarAporteRequest,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        correlation_id: str | None = Header(
            default=None,
            alias="X-Correlation-ID",
        ),
    ) -> JSONResponse:
        """Valida e processa um aporte de forma idempotente."""

        if not idempotency_key.strip():
            raise HTTPException(
                status_code=400,
                detail="Idempotency-Key não pode ser vazia.",
            )

        try:
            # Verifica se a chave já foi utilizada.
            anterior = consultar_resultado_anterior(
                idempotency_key=idempotency_key,
                campanha_id=dados.campanha_id,
                investidor_id=dados.investidor_id,
                valor_centavos=dados.valor,
                data_dir=data_dir,
            )

            if anterior is not None:
                return JSONResponse(
                    status_code=anterior.status_http,
                    content=anterior.resposta,
                )

            # Impede aportes de investidores bloqueados.
            if investidor_esta_bloqueado(
                dados.investidor_id,
                data_dir=data_dir,
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Investidor bloqueado não pode realizar aportes.",
                )

            # Aplica a política de limite de aporte.
            try:
                validar_limite_aporte(
                    investidor_id=dados.investidor_id,
                    valor=Valor(dados.valor),
                    data_dir=data_dir,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=str(exc),
                ) from exc

            # Consulta Campanhas com timeout e circuit breaker.
            try:
                aceita = await cliente.aceita_aportes(dados.campanha_id)

            except CampanhaIndisponivelError:
                # Registra a rejeição de forma idempotente.
                resultado = rejeitar_aporte(
                    idempotency_key=idempotency_key,
                    campanha_id=dados.campanha_id,
                    investidor_id=dados.investidor_id,
                    valor_centavos=dados.valor,
                    data_dir=data_dir,
                )

                return JSONResponse(
                    status_code=resultado.status_http,
                    content=resultado.resposta,
                )

            if not aceita:
                raise HTTPException(
                    status_code=409,
                    detail="A campanha não está aberta para aportes.",
                )

            # Confirma aporte e registra eventos na outbox.
            resultado = confirmar_aporte(
                idempotency_key=idempotency_key,
                campanha_id=dados.campanha_id,
                investidor_id=dados.investidor_id,
                valor_centavos=dados.valor,
                correlation_id=correlation_id or str(uuid4()),
                data_dir=data_dir,
            )

            return JSONResponse(
                status_code=resultado.status_http,
                content=resultado.resposta,
            )

        except ChaveIdempotenciaConflitante as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            ) from exc

    # ---------------------------------------------------------
    # GET /aportes/meus
    # ---------------------------------------------------------

    @api.get("/aportes/meus")
    def meus_aportes(
        authorization: str | None = Header(
            default=None,
            alias="Authorization",
        ),
        pagina: int = Query(default=1, ge=1),
        tamanho_pagina: int = Query(default=10, ge=1, le=100),
        campanha_id: str | None = Query(default=None),
    ) -> HistoricoPaginado:
        """Lista apenas os aportes do investidor autenticado.

        O identificador do investidor é extraído do JWT
        validado, nunca de um cabeçalho X-User-ID.
        """

        if authorization is None:
            raise HTTPException(
                status_code=401,
                detail="Token de autenticação obrigatório.",
            )

        esquema, _, token = authorization.partition(" ")

        if esquema.lower() != "bearer" or not token.strip():
            raise HTTPException(
                status_code=401,
                detail="Token de autenticação inválido.",
            )

        segredo, _ = segredo_do_ambiente()

        try:
            claims = validar_token(
                token.strip(),
                segredo=segredo,
            )
        except TokenInvalido as exc:
            raise HTTPException(
                status_code=401,
                detail="Token de autenticação inválido ou expirado.",
            ) from exc

        if claims.perfil != "INVESTIDOR":
            raise HTTPException(
                status_code=403,
                detail="Acesso permitido apenas para investidores.",
            )

        return listar_aportes_investidor(
            investidor_id=claims.sub,
            pagina=pagina,
            tamanho_pagina=tamanho_pagina,
            campanha_id=campanha_id,
            data_dir=data_dir,
        )

    # ---------------------------------------------------------
    # GET /aportes/campanha/{campanha_id}/resumo
    # ---------------------------------------------------------

    @api.get("/aportes/campanha/{campanha_id}/resumo")
    def resumo_campanha(
        campanha_id: str,
    ) -> ResumoCampanha:
        """Retorna total e quantidade de aportes confirmados."""

        if not campanha_id.strip():
            raise HTTPException(
                status_code=422,
                detail="O identificador da campanha é obrigatório.",
            )

        return obter_resumo_campanha(
            campanha_id=campanha_id,
            data_dir=data_dir,
        )

    return api
