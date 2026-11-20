"""Proteção dos identificadores de documentos KYC."""

from __future__ import annotations

import hashlib
import hmac
import os

SEGREDO_KYC_PADRAO = "segredo-kyc-hash-padrao-desenvolvimento-32b"


def gerar_hash_documento(tipo: str, numero: str) -> str:
    """Calcula HMAC-SHA256 sem persistir o número original."""
    segredo = os.getenv("KYC_HASH_SECRET", "").strip() or SEGREDO_KYC_PADRAO

    tipo_normalizado = tipo.strip().upper()
    numero_normalizado = "".join(caractere for caractere in numero if caractere.isalnum()).upper()

    if not tipo_normalizado or not numero_normalizado:
        raise ValueError("Tipo e número do documento são obrigatórios")

    mensagem = f"{tipo_normalizado}:{numero_normalizado}"

    return hmac.new(
        segredo.encode("utf-8"),
        mensagem.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
