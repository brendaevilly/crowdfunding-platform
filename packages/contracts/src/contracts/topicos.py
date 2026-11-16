"""Nomes de tópico do broker. Nunca escreva o texto do tópico fora daqui."""

from __future__ import annotations

from typing import Final

USUARIO_CADASTRADO: Final = "usuario.cadastrado"
USUARIO_STATUS_ALTERADO: Final = "usuario.status-alterado"
IDENTIDADE_VERIFICADA: Final = "identidade.verificada"
CAMPANHA_PUBLICADA: Final = "campanha.publicada"
TOTAL_ARRECADADO_ATUALIZADO: Final = "campanha.total-arrecadado-atualizado"
APORTE_CONFIRMADO: Final = "aporte.confirmado"
CAMPANHA_LIQUIDADA: Final = "campanha.liquidada"
RESULTADO_CAMPANHA: Final = "campanha.resultado"
RETORNO_DISTRIBUIDO: Final = "retorno.distribuido"

TODOS: Final = (
    USUARIO_CADASTRADO,
    USUARIO_STATUS_ALTERADO,
    IDENTIDADE_VERIFICADA,
    CAMPANHA_PUBLICADA,
    TOTAL_ARRECADADO_ATUALIZADO,
    APORTE_CONFIRMADO,
    CAMPANHA_LIQUIDADA,
    RESULTADO_CAMPANHA,
    RETORNO_DISTRIBUIDO,
)
