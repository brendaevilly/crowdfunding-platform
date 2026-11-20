"""Aplicação FastAPI do microsserviço Custódia e Retornos."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from contracts.topicos import (
    APORTE_CONFIRMADO,
    CAMPANHA_LIQUIDADA,
    CAMPANHA_PUBLICADA,
    RESULTADO_CAMPANHA,
)
from custodia_retornos.config import broker_url_padrao, custodia_url_padrao
from custodia_retornos.custodia.apuracao import apurar_pendentes
from custodia_retornos.custodia.clock import AdjustableClock, Clock, SystemClock
from custodia_retornos.custodia.consumidores import (
    consumir_aporte_confirmado,
    consumir_campanha_publicada,
    consumir_resultado_campanha,
)
from custodia_retornos.custodia.repositorio import listar_movimentacoes
from custodia_retornos.custodia.scheduler import executar_scheduler
from custodia_retornos.retornos.servico import (
    consumir_campanha_liquidada,
    listar_participacoes_investidor,
)
from custodia_retornos.retornos.servico_distribuicao import (
    distribuir_retornos,
    listar_extrato_investidor,
)
from shared.auth import TokenInvalido, segredo_do_ambiente, validar_token
from shared.consumer import EventHandler
from shared.db import migrate, transaction
from shared.http.app import create_app
from shared.messaging import configure_messaging
from shared.messaging_schema import install_messaging_schema

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

HANDLERS: dict[str, EventHandler] = {
    CAMPANHA_PUBLICADA: consumir_campanha_publicada,
    APORTE_CONFIRMADO: consumir_aporte_confirmado,
    RESULTADO_CAMPANHA: consumir_resultado_campanha,
    CAMPANHA_LIQUIDADA: consumir_campanha_liquidada,
}


class DistribuirRetornosRequest(BaseModel):
    valor_total: int = Field(gt=0, alias="valorTotal")


class ClockAdvanceRequest(BaseModel):
    seconds: float = Field(gt=0)


def criar_custodia_app(
    data_dir: str | Path = "data",
    *,
    clock: Clock | None = None,
    dev_mode: bool | None = None,
    scheduler_enabled: bool = True,
) -> FastAPI:
    """Cria a aplicação FastAPI de Custódia e Retornos."""

    app = create_app("custodia_retornos", version="0.1.0")

    if dev_mode is None:
        dev_mode = os.getenv("CUSTODIA_DEV_MODE", "false").lower() in ("true", "1", "yes")

    if clock is None:
        clock = AdjustableClock() if dev_mode else SystemClock()

    relogio = clock

    if dev_mode:

        @app.post("/_dev/clock/advance")
        def advance_clock(request: ClockAdvanceRequest) -> dict[str, object]:
            if not isinstance(relogio, AdjustableClock):
                raise HTTPException(
                    status_code=409,
                    detail="Relógio não é ajustável",
                )
            agora = relogio.advance(request.seconds)
            quantidade = apurar_pendentes(relogio, data_dir)
            return {
                "now": agora.isoformat(),
                "apuradas": quantidade,
            }

    @app.get("/custodia/campanhas/{campanha_id}/extrato")
    def consultar_extrato(campanha_id: str) -> dict[str, object]:
        """Retorna o extrato financeiro completo de uma campanha."""

        def consultar(conn: sqlite3.Connection) -> dict[str, object]:
            conta = conn.execute(
                """
                SELECT campanha_id, empreendedor_id, meta,
                       saldo_retido, prazo_fim
                FROM custodia_contas
                WHERE campanha_id = ?
                """,
                (campanha_id,),
            ).fetchone()

            if conta is None:
                raise HTTPException(
                    status_code=404,
                    detail="Conta de custódia não encontrada",
                )

            movimentacoes = listar_movimentacoes(conn, campanha_id)

            liquidacao = conn.execute(
                """
                SELECT resultado, valor_bruto, taxa_plataforma,
                       valor_liquido, liquidada_em
                FROM custodia_liquidacoes
                WHERE campanha_id = ?
                """,
                (campanha_id,),
            ).fetchone()

            return {
                "campanha_id": str(conta[0]),
                "empreendedor_id": conta[1],
                "meta": int(conta[2]),
                "saldo_retido": int(conta[3]),
                "prazo_fim": str(conta[4]),
                "movimentacoes": [
                    {
                        "movimentacao_id": m.movimentacao_id,
                        "aporte_id": m.aporte_id,
                        "tipo": m.tipo.value,
                        "valor": m.valor,
                        "criada_em": m.criada_em.isoformat(),
                    }
                    for m in movimentacoes
                ],
                "liquidacao": (
                    {
                        "resultado": str(liquidacao[0]),
                        "valor_bruto": int(liquidacao[1]),
                        "taxa_plataforma": int(liquidacao[2]),
                        "valor_liquido": int(liquidacao[3]),
                        "liquidada_em": str(liquidacao[4]),
                    }
                    if liquidacao is not None
                    else None
                ),
            }

        return transaction(
            consultar,
            "custodia_retornos",
            data_dir,
        )

    @app.get("/retornos/minhas-participacoes")
    def minhas_participacoes(
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> list[dict[str, object]]:
        """Lista as participações do investidor autenticado."""

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
            claims = validar_token(token.strip(), segredo=segredo)
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

        return transaction(
            lambda conn: listar_participacoes_investidor(
                conn,
                claims.sub,
            ),
            "custodia_retornos",
            data_dir,
        )

    @app.post("/retornos/campanhas/{campanha_id}/distribuir")
    def distribuir_retornos_http(
        campanha_id: str,
        payload: DistribuirRetornosRequest,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> dict[str, object]:
        """Distribui retornos somente pelo empreendedor proprietário."""

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
            claims = validar_token(token.strip(), segredo=segredo)
        except TokenInvalido as exc:
            raise HTTPException(
                status_code=401,
                detail="Token de autenticação inválido ou expirado.",
            ) from exc

        if claims.perfil != "EMPREENDEDOR":
            raise HTTPException(
                status_code=403,
                detail="Acesso permitido apenas para empreendedores.",
            )

        try:
            distribuicoes = transaction(
                lambda conn: distribuir_retornos(
                    conn,
                    campanha_id,
                    claims.sub,
                    payload.valor_total,
                ),
                "custodia_retornos",
                data_dir,
            )
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            codigo = 404 if str(exc) == "Campanha não encontrada" else 400
            raise HTTPException(
                status_code=codigo,
                detail=str(exc),
            ) from exc

        return {
            "campanhaId": campanha_id,
            "valorTotal": payload.valor_total,
            "distribuicoes": distribuicoes,
        }

    @app.get("/retornos/extrato")
    def extrato_retornos_http(
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> list[dict[str, object]]:
        """Lista os retornos recebidos pelo investidor autenticado."""

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
            claims = validar_token(token.strip(), segredo=segredo)
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

        return transaction(
            lambda conn: listar_extrato_investidor(conn, claims.sub),
            "custodia_retornos",
            data_dir,
        )

    @asynccontextmanager
    async def custodia_lifespan(application: FastAPI) -> AsyncIterator[None]:
        migrate("custodia_retornos", MIGRATIONS_DIR, data_dir)
        install_messaging_schema("custodia_retornos", data_dir)
        logger.info("Migrations da Custódia aplicadas com sucesso.")
        tarefa = None
        if scheduler_enabled:
            tarefa = asyncio.create_task(
                executar_scheduler(relogio, data_dir),
                name="custodia-scheduler",
            )
        try:
            yield
        finally:
            if tarefa is not None:
                tarefa.cancel()
                await asyncio.gather(tarefa, return_exceptions=True)

    app.router.lifespan_context = custodia_lifespan

    habilitar_messaging = os.getenv(
        "CUSTODIA_RETORNOS_MESSAGING_ENABLED",
        "true",
    ).lower() in ("true", "1", "yes")

    if habilitar_messaging:
        configure_messaging(
            app,
            service="custodia_retornos",
            service_url=custodia_url_padrao(),
            broker_url=broker_url_padrao(),
            handlers=HANDLERS,
            data_dir=data_dir,
        )

    return app


app = criar_custodia_app()
