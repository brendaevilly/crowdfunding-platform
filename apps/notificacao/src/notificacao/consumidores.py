"""Consumidores de eventos assíncronos para o serviço de Notificação."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from contracts.eventos import (
    AporteConfirmado,
    IdentidadeVerificada,
    ResultadoCampanha,
    RetornoDistribuido,
)
from notificacao.canal import CanalNotificacao, canal_padrao
from notificacao.domain import Notificacao, StatusEnvio
from notificacao.repository import salvar_notificacao

logger = logging.getLogger(__name__)


def _despachar_e_salvar(
    conn: sqlite3.Connection,
    *,
    usuario_id: str,
    evento_origem_id: str,
    tipo_evento: str,
    titulo: str,
    mensagem: str,
    canal: CanalNotificacao | None = None,
) -> bool:
    """Tenta enviar pelo canal simulado e persiste a notificação no banco de dados.

    Idempotente por (usuario_id, evento_origem_id): se já existir registro, a operação é ignorada.
    Falhas no canal nunca disparam exceção: são registradas com status FALHA.
    """
    row = conn.execute(
        "SELECT id FROM notificacao WHERE usuario_id = ? AND evento_origem_id = ?",
        (usuario_id, evento_origem_id),
    ).fetchone()

    if row is not None:
        logger.info(
            "Notificação já existente para usuário %s e evento %s. Reentrega ignorada.",
            usuario_id,
            evento_origem_id,
        )
        return False

    canal_ativo = canal or canal_padrao

    try:
        enviado = canal_ativo.enviar(usuario_id, titulo, mensagem)
    except Exception as exc:
        logger.error(
            "Exceção capturada no canal de envio para usuário %s: %s",
            usuario_id,
            exc,
        )
        enviado = False

    status_envio = StatusEnvio.ENVIADA if enviado else StatusEnvio.FALHA

    notificacao = Notificacao.criar(
        usuario_id=usuario_id,
        evento_origem_id=evento_origem_id,
        tipo_evento=tipo_evento,
        titulo=titulo,
        mensagem=mensagem,
        status_envio=status_envio,
    )
    salvar_notificacao(conn, notificacao)
    return True


def consumir_aporte_confirmado(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    canal: CanalNotificacao | None = None,
) -> None:
    """Notifica o investidor sobre a confirmação de seu aporte."""
    evento = AporteConfirmado.model_validate(payload)
    valor_reais = evento.valor / 100.0

    _despachar_e_salvar(
        conn,
        usuario_id=evento.investidor_id,
        evento_origem_id=evento.aporte_id,
        tipo_evento="aporte.confirmado",
        titulo="Aporte Confirmado",
        mensagem=(
            f"Seu aporte no valor de R$ {valor_reais:.2f} na campanha "
            f"{evento.campanha_id} foi confirmado com sucesso."
        ),
        canal=canal,
    )


def consumir_resultado_campanha(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    canal: CanalNotificacao | None = None,
) -> None:
    """Notifica o empreendedor e todos os investidores sobre o encerramento da campanha."""
    evento = ResultadoCampanha.model_validate(payload)
    valor_reais = evento.valor_arrecadado / 100.0
    origem_id = f"{evento.campanha_id}:resultado"

    # 1. Notifica o empreendedor
    _despachar_e_salvar(
        conn,
        usuario_id=evento.empreendedor_id,
        evento_origem_id=origem_id,
        tipo_evento="campanha.resultado",
        titulo=f"Campanha Finalizada: {evento.resultado.value}",
        mensagem=(
            f"Sua campanha {evento.campanha_id} foi encerrada com resultado "
            f"{evento.resultado.value}. Total arrecadado: R$ {valor_reais:.2f}."
        ),
        canal=canal,
    )

    # 2. Notifica cada investidor participante
    for investidor_id in evento.investidor_ids:
        _despachar_e_salvar(
            conn,
            usuario_id=investidor_id,
            evento_origem_id=origem_id,
            tipo_evento="campanha.resultado",
            titulo=f"Resultado da Campanha: {evento.resultado.value}",
            mensagem=(
                f"A campanha {evento.campanha_id} em que você investiu foi "
                f"finalizada com resultado {evento.resultado.value}."
            ),
            canal=canal,
        )


def consumir_retorno_distribuido(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    canal: CanalNotificacao | None = None,
) -> None:
    """Notifica o investidor sobre a distribuição de rendimento/retorno financeiro."""
    evento = RetornoDistribuido.model_validate(payload)
    valor_reais = evento.valor / 100.0

    _despachar_e_salvar(
        conn,
        usuario_id=evento.investidor_id,
        evento_origem_id=evento.retorno_id,
        tipo_evento="retorno.distribuido",
        titulo="Retorno Distribuído",
        mensagem=(
            f"Você recebeu uma distribuição de retorno no valor de "
            f"R$ {valor_reais:.2f} referente à campanha {evento.campanha_id}."
        ),
        canal=canal,
    )


def consumir_identidade_verificada(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    canal: CanalNotificacao | None = None,
) -> None:
    """Notifica o usuário sobre a aprovação e verificação de sua identidade (KYC)."""
    evento = IdentidadeVerificada.model_validate(payload)

    _despachar_e_salvar(
        conn,
        usuario_id=evento.usuario_id,
        evento_origem_id=f"{evento.usuario_id}:identidade-verificada",
        tipo_evento="identidade.verificada",
        titulo="Identidade Verificada",
        mensagem="Sua documentação de identidade foi verificada e aprovada com sucesso.",
        canal=canal,
    )
