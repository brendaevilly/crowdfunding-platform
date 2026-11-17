"""Rate limit em memória (token bucket) por chave: usuário autenticado ou IP."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

_LIMITE_PARA_LIMPAR = 10_000


@dataclass(frozen=True)
class Decisao:
    permitido: bool
    retry_after: int  # segundos até haver um token (0 quando permitido)


class LimitadorTaxa:
    """`limite` requisições por `janela` segundos, com rajada de até `limite`."""

    def __init__(
        self, limite: int, janela: float, relogio: Callable[[], float] = time.monotonic
    ) -> None:
        if limite <= 0 or janela <= 0:
            raise ValueError("limite e janela devem ser positivos")
        self.limite = limite
        self.janela = janela
        self._taxa = limite / janela  # tokens por segundo
        self._relogio = relogio
        self._baldes: dict[str, tuple[float, float]] = {}  # chave -> (tokens, última atualização)

    def permitir(self, chave: str) -> Decisao:
        agora = self._relogio()
        tokens, ultimo = self._baldes.get(chave, (float(self.limite), agora))
        tokens = min(float(self.limite), tokens + (agora - ultimo) * self._taxa)
        if tokens >= 1.0:
            self._baldes[chave] = (tokens - 1.0, agora)
            self._limpar(agora)
            return Decisao(True, 0)
        self._baldes[chave] = (tokens, agora)
        return Decisao(False, max(1, math.ceil((1.0 - tokens) / self._taxa)))

    def _limpar(self, agora: float) -> None:
        """Descarta baldes que já voltaram a ficar cheios (evita crescer sem limite)."""
        if len(self._baldes) < _LIMITE_PARA_LIMPAR:
            return
        cheios = [
            k for k, (t, u) in self._baldes.items() if t + (agora - u) * self._taxa >= self.limite
        ]
        for chave in cheios:
            del self._baldes[chave]
