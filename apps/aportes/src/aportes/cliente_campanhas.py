"""Consulta o status de campanhas com timeout e circuit breaker."""

import httpx

from contracts.campanhas_api import (
    CampanhaStatusResponse,
    caminho_status_campanha,
)
from shared.http.client import ServiceClient
from shared.resilience import CircuitBreaker, CircuitOpenError


class CampanhaIndisponivelError(Exception):
    """Não foi possível consultar o status da campanha."""


class ClienteCampanhas:
    """Cliente HTTP para verificar se uma campanha aceita aportes."""

    def __init__(
        self,
        *,
        timeout: float = 5.0,
        circuit_breaker: CircuitBreaker | None = None,
        client: ServiceClient | None = None,
    ) -> None:
        self.timeout = timeout
        self.circuit_breaker = circuit_breaker if circuit_breaker is not None else CircuitBreaker()
        self.client = client if client is not None else ServiceClient("campanhas", timeout=timeout)

    async def consultar_status(
        self,
        campanha_id: str,
    ) -> CampanhaStatusResponse:
        """Consulta o status da campanha com proteção contra falhas."""

        async def operacao() -> CampanhaStatusResponse:
            caminho = caminho_status_campanha(campanha_id)

            resposta = await self.client.get(caminho)
            resposta.raise_for_status()

            return CampanhaStatusResponse.model_validate(resposta.json())

        try:
            return await self.circuit_breaker.call(operacao)
        except (
            httpx.HTTPError,
            CircuitOpenError,
            ValueError,
        ) as exc:
            raise CampanhaIndisponivelError(
                "Não foi possível consultar o status da campanha."
            ) from exc

    async def aceita_aportes(self, campanha_id: str) -> bool:
        """Retorna True somente para campanhas publicadas."""
        status = await self.consultar_status(campanha_id)
        return status.aceita_aportes

    async def aclose(self) -> None:
        """Encerra as conexões HTTP."""
        await self.client.aclose()
