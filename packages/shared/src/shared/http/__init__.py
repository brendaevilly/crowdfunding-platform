"""Base HTTP dos serviços: create_app, middleware de correlation-id, erros e cliente."""

from shared.http.app import HealthResponse, create_app
from shared.http.client import ERROS_DE_CONEXAO, ERROS_DE_TIMEOUT, ServiceClient
from shared.http.errors import AppError, ErrorResponse
from shared.http.runner import run

__all__ = [
    "ERROS_DE_CONEXAO",
    "ERROS_DE_TIMEOUT",
    "AppError",
    "ErrorResponse",
    "HealthResponse",
    "ServiceClient",
    "create_app",
    "run",
]
