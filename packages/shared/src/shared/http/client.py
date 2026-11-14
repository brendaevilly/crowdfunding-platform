"""Cliente HTTP service-to-service (httpx) com timeout e propagação do correlation-id."""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

from shared.config import Settings, service_url
from shared.correlation import CORRELATION_HEADER, get_correlation_id


class ServiceClient:
    """Use `ServiceClient('campanhas')` (URL via services.json) ou `base_url=...`.

    O timeout vem do argumento ou de HTTP_TIMEOUT_SECONDS (padrão 5s).
    """

    def __init__(
        self,
        service: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if (service is None) == (base_url is None):
            raise ValueError("informe exatamente um entre 'service' e 'base_url'")
        url = base_url if base_url is not None else service_url(str(service))
        self.timeout = timeout if timeout is not None else Settings.from_env().http_timeout
        self._client = httpx.AsyncClient(base_url=url, timeout=self.timeout, transport=transport)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        headers = httpx.Headers(kwargs.pop("headers", None) or {})
        cid = get_correlation_id()
        if cid and CORRELATION_HEADER not in headers:
            headers[CORRELATION_HEADER] = cid
        return await self._client.request(method, url, headers=headers, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", url, **kwargs)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ServiceClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
