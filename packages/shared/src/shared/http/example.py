"""Servidor de exemplo: `uv run python -m shared.http.example` e abra http://127.0.0.1:3099/health."""

from __future__ import annotations

from pydantic import BaseModel, Field

from shared.http.app import create_app
from shared.http.errors import AppError
from shared.http.runner import run

app = create_app("exemplo")


class EcoEntrada(BaseModel):
    texto: str = Field(min_length=1, max_length=100)


class EcoSaida(BaseModel):
    texto: str
    tamanho: int


@app.post("/eco", response_model=EcoSaida)
async def eco(entrada: EcoEntrada) -> EcoSaida:
    if entrada.texto == "erro":
        raise AppError(409, "exemplo_conflito", "Texto 'erro' não é permitido.")
    return EcoSaida(texto=entrada.texto, tamanho=len(entrada.texto))


if __name__ == "__main__":
    run(app, "exemplo", port=3099)
