"""Microsserviço de Identidade (Contas + KYC)."""

from identidade.app import app, criar_identidade_app

__all__ = ["app", "criar_identidade_app"]
