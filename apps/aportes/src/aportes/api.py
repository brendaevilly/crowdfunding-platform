"""Endpoint HTTP para criação de aportes."""

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from aportes.cliente_campanhas import (
    CampanhaIndisponivelError,
    ClienteCampanhas,
)
from aportes.domain import Valor
from aportes.politica_limite_aporte import validar_limite_aporte
from aportes.processamento import (
    ChaveIdempotenciaConflitante,
    confirmar_aporte,
    consultar_resultado_anterior,
    rejeitar_aporte,
)
from aportes.status_investidor import investidor_esta_bloqueado


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
            # Consulta primeiro a chave para evitar operações duplicadas.
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

            # Consulta Campanhas usando timeout e circuit breaker.
            try:
                aceita = await cliente.aceita_aportes(dados.campanha_id)

            except CampanhaIndisponivelError:
                # Fail-safe: não confirma o aporte quando
                # Campanhas estiver indisponível.
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

            # Confirma aporte, outbox e pendência de Custódia.
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

    return api
