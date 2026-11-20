"""Canal simulado de envio de notificações (e-mail, SMS, push)."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


class CanalNotificacao:
    """Simulador de canal de envio externo com retentativas locais resilientes."""

    def __init__(self, tentativas_maximas: int = 3) -> None:
        self.tentativas_maximas = max(1, tentativas_maximas)

    def enviar(self, usuario_id: str, titulo: str, mensagem: str) -> bool:
        """Tenta enviar a notificação pelo canal simulado.

        Falhas NUNCA propagam exceção para o chamador: executa tentativas internas e,
        se persistir a falha, registra em log e retorna False.
        """
        for tentativa in range(1, self.tentativas_maximas + 1):
            try:
                sucesso = self._executar_envio(usuario_id, titulo, mensagem)
                if sucesso:
                    logger.info(
                        "Notificação enviada com sucesso para usuário %s: '%s' (tentativa %d/%d)",
                        usuario_id,
                        titulo,
                        tentativa,
                        self.tentativas_maximas,
                    )
                    return True
                logger.warning(
                    "Tentativa %d/%d de envio para usuário %s falhou.",
                    tentativa,
                    self.tentativas_maximas,
                    usuario_id,
                )
            except Exception as exc:
                logger.warning(
                    "Exceção na tentativa %d/%d de envio para usuário %s: %s",
                    tentativa,
                    self.tentativas_maximas,
                    usuario_id,
                    exc,
                )

        logger.error(
            "Falha definitiva ao enviar notificação para usuário %s após %d tentativas.",
            usuario_id,
            self.tentativas_maximas,
        )
        return False

    def _executar_envio(self, usuario_id: str, titulo: str, mensagem: str) -> bool:
        """Execução da simulação física do canal.

        Pode ser configurado para falhar em testes via variável de ambiente.
        """
        if os.getenv("NOTIFICACAO_SIMULAR_FALHA", "false").lower() in ("true", "1", "yes"):
            return False

        logger.info(
            "[CANAL SIMULADO] Destinatário: %s | Título: %s | Mensagem: %s",
            usuario_id,
            titulo,
            mensagem,
        )
        return True


canal_padrao = CanalNotificacao()
