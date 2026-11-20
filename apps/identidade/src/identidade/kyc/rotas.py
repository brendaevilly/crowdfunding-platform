"""Rotas HTTP de verificação de identidade."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from identidade.contas.rotas import _autenticar_requisicao, _exigir_administrador
from identidade.kyc.decisao import (
    DecisaoKycNaoPermitidaErro,
    decidir_verificacao_kyc,
)
from identidade.kyc.dominio import StatusVerificacao, VerificacaoIdentidade
from identidade.kyc.mock_provider import criar_mock_provider
from identidade.kyc.servico import (
    NovaVerificacaoNaoPermitidaErro,
    VerificacaoKycNaoEncontradaErro,
    consultar_status_kyc,
    registrar_documento_kyc,
    solicitar_nova_verificacao,
    verificar_documento_com_provider,
)


class DocumentoKycRequest(BaseModel):
    """Dados recebidos para registro do documento."""

    tipo: str = Field(min_length=1, max_length=30)
    numero: str = Field(min_length=1, max_length=100)


class DecisaoKycRequest(BaseModel):
    """Decisão administrativa sobre uma verificação KYC."""

    status: StatusVerificacao


class StatusKycResponse(BaseModel):
    """Resposta pública sem dados sensíveis do documento."""

    verificacaoId: str
    status: str
    documentoTipo: str | None = None


def _para_response(
    verificacao: VerificacaoIdentidade,
) -> StatusKycResponse:
    return StatusKycResponse(
        verificacaoId=verificacao.id,
        status=verificacao.status.value,
        documentoTipo=verificacao.documento_tipo,
    )


def criar_kyc_router(data_dir: str | Path = "data") -> APIRouter:
    """Cria as rotas autenticadas do módulo KYC."""
    router = APIRouter(prefix="/kyc", tags=["kyc"])

    @router.post(
        "/documentos",
        response_model=StatusKycResponse,
        status_code=status.HTTP_200_OK,
    )
    def post_documentos(
        body: DocumentoKycRequest,
        request: Request,
    ) -> StatusKycResponse:
        usuario = _autenticar_requisicao(request, data_dir)

        try:
            modo = os.getenv("KYC_VERIFICATION_MODE", "auto").strip().lower()

            if modo == "manual":
                verificacao = registrar_documento_kyc(
                    usuario.id,
                    tipo=body.tipo,
                    numero=body.numero,
                    data_dir=data_dir,
                )
            elif modo == "auto":
                verificacao = verificar_documento_com_provider(
                    usuario.id,
                    tipo=body.tipo,
                    numero=body.numero,
                    provider=criar_mock_provider(),
                    data_dir=data_dir,
                )
            else:
                raise RuntimeError("KYC_VERIFICATION_MODE deve ser 'auto' ou 'manual'")
        except (VerificacaoKycNaoEncontradaErro, DecisaoKycNaoPermitidaErro) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        return _para_response(verificacao)

    @router.post(
        "/verificacoes",
        response_model=StatusKycResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def post_nova_verificacao(request: Request) -> StatusKycResponse:
        """Solicita nova verificação após reprovação ou expiração."""
        usuario = _autenticar_requisicao(request, data_dir)

        try:
            verificacao = solicitar_nova_verificacao(
                usuario.id,
                data_dir=data_dir,
            )
        except NovaVerificacaoNaoPermitidaErro as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        return _para_response(verificacao)

    @router.get(
        "/status",
        response_model=StatusKycResponse,
    )
    def get_status(request: Request) -> StatusKycResponse:
        usuario = _autenticar_requisicao(request, data_dir)
        verificacao = consultar_status_kyc(usuario.id, data_dir)

        if verificacao is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nenhuma verificação KYC encontrada",
            )

        return _para_response(verificacao)

    @router.post(
        "/admin/verificacoes/{usuario_id}/decisao",
        response_model=StatusKycResponse,
    )
    def post_decisao_admin(
        usuario_id: str,
        body: DecisaoKycRequest,
        request: Request,
    ) -> StatusKycResponse:
        """Permite decisão manual exclusivamente por ADMIN."""

        _exigir_administrador(request, data_dir)

        try:
            verificacao = decidir_verificacao_kyc(
                usuario_id,
                status=body.status,
                data_dir=data_dir,
            )
        except DecisaoKycNaoPermitidaErro as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        return _para_response(verificacao)

    return router
