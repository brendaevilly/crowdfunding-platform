"""Contrato síncrono Aportes -> Campanhas: GET /campanhas/:id/status (contrato 2.3)."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from contracts.base import Contrato, Id

CAMPANHA_STATUS_PATH: Final = "/campanhas/{campanha_id}/status"


class StatusCampanha(StrEnum):
    RASCUNHO = "RASCUNHO"
    PUBLICADA = "PUBLICADA"  # única que aceita aportes
    ENCERRADA = "ENCERRADA"
    CANCELADA = "CANCELADA"


class CampanhaStatusResponse(Contrato):
    campanha_id: Id
    status: StatusCampanha

    @property
    def aceita_aportes(self) -> bool:
        return self.status is StatusCampanha.PUBLICADA


def caminho_status_campanha(campanha_id: str) -> str:
    return CAMPANHA_STATUS_PATH.format(campanha_id=campanha_id)
