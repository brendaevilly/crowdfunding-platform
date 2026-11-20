"""Modelo de domínio do serviço de Notificação."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


class StatusEnvio(StrEnum):
    """Estado do envio da notificação pelo canal simulado."""

    ENVIADA = "ENVIADA"
    FALHA = "FALHA"


@dataclass
class Notificacao:
    """Entidade que representa uma notificação gerada para um usuário."""

    id: str
    usuario_id: str
    evento_origem_id: str
    tipo_evento: str
    titulo: str
    mensagem: str
    status_envio: StatusEnvio
    lida: bool = False
    criado_em: datetime | None = None
    enviado_em: datetime | None = None

    @classmethod
    def criar(
        cls,
        *,
        usuario_id: str,
        evento_origem_id: str,
        tipo_evento: str,
        titulo: str,
        mensagem: str,
        status_envio: StatusEnvio,
        enviado_em: datetime | None = None,
        notificacao_id: str | None = None,
    ) -> Notificacao:
        """Fábrica de nova notificação."""
        nid = notificacao_id or str(uuid4())
        agora = datetime.now(UTC)
        return cls(
            id=nid,
            usuario_id=usuario_id,
            evento_origem_id=evento_origem_id,
            tipo_evento=tipo_evento,
            titulo=titulo,
            mensagem=mensagem,
            status_envio=status_envio,
            lida=False,
            criado_em=agora,
            enviado_em=enviado_em or (agora if status_envio == StatusEnvio.ENVIADA else None),
        )

    def marcar_como_lida(self) -> None:
        """Marca a notificação como lida."""
        self.lida = True
