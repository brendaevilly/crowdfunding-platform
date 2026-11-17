from __future__ import annotations

import pytest

from gateway.ratelimit import LimitadorTaxa
from gateway.rotas import CaminhoInvalido, Destino, resolver, rota_publica


@pytest.mark.parametrize(
    ("caminho", "esperado"),
    [
        ("/api/campanhas/abc/status", Destino("campanhas", "/campanhas/abc/status")),
        ("/api/campanhas", Destino("campanhas", "/campanhas")),
        ("/api/campanhas/", Destino("campanhas", "/campanhas/")),
        ("/api/aportes", Destino("aportes", "/aportes")),
        ("/api/retornos/meus", Destino("custodia_retornos", "/retornos/meus")),
        ("/api/notificacoes/u1", Destino("notificacao", "/notificacoes/u1")),
        ("/api/identidade/login", Destino("identidade", "/identidade/login")),
    ],
)
def test_resolver_rotas(caminho: str, esperado: Destino) -> None:
    assert resolver(caminho) == esperado


@pytest.mark.parametrize(
    "caminho", ["/", "/health", "/api", "/api/", "/api/xyz/1", "/apix/aportes"]
)
def test_resolver_sem_rota(caminho: str) -> None:
    assert resolver(caminho) is None


@pytest.mark.parametrize(
    "caminho", ["/api/campanhas/../identidade", "/api/aportes/./x", "/api/aportes/.."]
)
def test_resolver_rejeita_segmentos_perigosos(caminho: str) -> None:
    with pytest.raises(CaminhoInvalido):
        resolver(caminho)


def test_rotas_publicas_sao_so_cadastro_e_login() -> None:
    assert rota_publica("POST", "/api/identidade/usuarios")
    assert rota_publica("post", "/api/identidade/login/")
    assert not rota_publica("GET", "/api/identidade/usuarios")
    assert not rota_publica("POST", "/api/aportes")
    assert not rota_publica("POST", "/api/identidade/usuarios/u1/perfil")


class Relogio:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_limitador_bloqueia_apos_o_limite_e_informa_retry_after() -> None:
    relogio = Relogio()
    lim = LimitadorTaxa(3, 60, relogio)
    assert [lim.permitir("a").permitido for _ in range(3)] == [True, True, True]
    negado = lim.permitir("a")
    assert negado.permitido is False
    assert negado.retry_after == 20  # 60s / 3 tokens


def test_limitador_repoe_tokens_com_o_tempo() -> None:
    relogio = Relogio()
    lim = LimitadorTaxa(2, 10, relogio)
    lim.permitir("a")
    lim.permitir("a")
    assert lim.permitir("a").permitido is False
    relogio.t += 5  # 1 token a cada 5s
    assert lim.permitir("a").permitido is True
    assert lim.permitir("a").permitido is False


def test_limitador_isola_chaves() -> None:
    lim = LimitadorTaxa(1, 60, Relogio())
    assert lim.permitir("user:1").permitido
    assert not lim.permitir("user:1").permitido
    assert lim.permitir("user:2").permitido
    assert lim.permitir("ip:1.2.3.4").permitido


def test_limitador_nao_passa_da_capacidade_apos_ficar_ocioso() -> None:
    relogio = Relogio()
    lim = LimitadorTaxa(2, 10, relogio)
    lim.permitir("a")
    relogio.t += 10_000
    assert [lim.permitir("a").permitido for _ in range(3)] == [True, True, False]


def test_limitador_valida_parametros() -> None:
    with pytest.raises(ValueError):
        LimitadorTaxa(0, 10)
    with pytest.raises(ValueError):
        LimitadorTaxa(10, 0)
