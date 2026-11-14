"""Corpo de erro padronizado: {"error": {"code", "message", "details", "correlationId"}}."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from shared.correlation import get_correlation_id


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None
    correlationId: str | None = None  # noqa: N815 (formato do contrato JSON)


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    """Erro de negócio com status HTTP e código estável (use nas rotas)."""

    def __init__(
        self, status_code: int, code: str, message: str, details: Any | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    corpo = ErrorResponse(
        error=ErrorBody(
            code=code, message=message, details=details, correlationId=get_correlation_id()
        )
    )
    return JSONResponse(
        corpo.model_dump(mode="json"),
        status_code=status_code,
        headers=headers,
    )


def _codigo_http(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        429: "too_many_requests",
    }.get(status_code, "http_error")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        headers = dict(exc.headers) if exc.headers else None
        return error_response(
            exc.status_code, _codigo_http(exc.status_code), str(exc.detail), headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        detalhes = [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
        ]
        return error_response(422, "validation_error", "Dados inválidos.", detalhes)
