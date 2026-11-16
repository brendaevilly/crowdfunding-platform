"""Instâncias válidas de cada evento, para testes de contrato dos serviços e deste pacote."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from contracts.base import Contrato
from contracts.eventos import (
    AporteConfirmado,
    CampanhaLiquidada,
    CampanhaPublicada,
    IdentidadeVerificada,
    Perfil,
    ResultadoCampanha,
    ResultadoFinal,
    RetornoDistribuido,
    StatusUsuario,
    TotalArrecadadoAtualizado,
    UsuarioCadastrado,
    UsuarioStatusAlterado,
)

AGORA = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def exemplos() -> list[Contrato]:
    return [
        UsuarioCadastrado(usuario_id="u1", perfil=Perfil.INVESTIDOR, cadastrado_em=AGORA),
        UsuarioStatusAlterado(
            usuario_id="u1",
            status_anterior=StatusUsuario.ATIVO,
            status_novo=StatusUsuario.BLOQUEADO,
            alterado_em=AGORA,
        ),
        IdentidadeVerificada(usuario_id="u1", verificada_em=AGORA),
        CampanhaPublicada(
            campanha_id="c1",
            empreendedor_id="e1",
            meta=100_000,
            prazo_fim=AGORA + timedelta(days=30),
        ),
        TotalArrecadadoAtualizado(campanha_id="c1", valor_acumulado=2_500),
        AporteConfirmado(
            aporte_id="a1", campanha_id="c1", investidor_id="u1", valor=500, confirmado_em=AGORA
        ),
        CampanhaLiquidada(
            campanha_id="c1",
            valor_bruto=1_000,
            taxa_plataforma=50,
            valor_liquido=950,
            liquidada_em=AGORA,
        ),
        ResultadoCampanha(
            campanha_id="c1",
            empreendedor_id="e1",
            resultado=ResultadoFinal.SUCESSO,
            valor_arrecadado=1_000,
            investidor_ids=("u1", "u2"),
            encerrada_em=AGORA,
        ),
        RetornoDistribuido(
            retorno_id="r1",
            campanha_id="c1",
            investidor_id="u1",
            valor=120,
            evento_origem_id="ev1",
            distribuido_em=AGORA,
        ),
    ]
