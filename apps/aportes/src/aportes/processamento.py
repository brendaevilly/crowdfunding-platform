"""Persistência transacional e idempotente de aportes."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from aportes.domain import Aporte, Valor
from aportes.repository import salvar_aporte_na_transacao
from contracts.eventos import AporteConfirmado, TotalArrecadadoAtualizado
from contracts.topicos import (
    APORTE_CONFIRMADO,
    TOTAL_ARRECADADO_ATUALIZADO,
)
from shared.db import transaction
from shared.outbox import OutboxEvent, add


@dataclass(frozen=True)
class ResultadoAporte:
    """Resultado persistido de uma requisição de aporte."""

    status_http: int
    resposta: dict[str, str | int]


class ChaveIdempotenciaConflitante(ValueError):
    """A chave já foi utilizada com dados diferentes."""


def confirmar_aporte(
    *,
    idempotency_key: str,
    campanha_id: str,
    investidor_id: str,
    valor_centavos: int,
    correlation_id: str,
    data_dir: str | Path = "data",
) -> ResultadoAporte:
    """Confirma aporte, eventos e pendência de Custódia atomicamente."""

    if not idempotency_key.strip():
        raise ValueError("Idempotency-Key é obrigatória")

    valor = Valor(valor_centavos)

    def operacao(conn: sqlite3.Connection) -> ResultadoAporte:
        existente = conn.execute(
            """
            SELECT campanha_id, investidor_id, valor,
                   status_http, resposta_json
            FROM aporte_requisicao
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()

        if existente is not None:
            (
                campanha_anterior,
                investidor_anterior,
                valor_anterior,
                status,
                resposta_anterior,
            ) = existente

            if (
                campanha_anterior != campanha_id
                or investidor_anterior != investidor_id
                or valor_anterior != valor_centavos
            ):
                raise ChaveIdempotenciaConflitante(
                    "Idempotency-Key já utilizada com dados diferentes"
                )

            return ResultadoAporte(
                status_http=int(status),
                resposta=json.loads(resposta_anterior),
            )

        aporte = Aporte(
            id=str(uuid4()),
            campanha_id=campanha_id,
            investidor_id=investidor_id,
            valor=valor,
        ).confirmar()

        # Salva o aporte confirmado.
        salvar_aporte_na_transacao(conn, aporte)

        # Registra a pendência de reconciliação com Custódia.
        # Tudo participa da mesma transação.
        conn.execute(
            """
            INSERT INTO aporte_custodia (
                aporte_id,
                status
            )
            VALUES (?, 'PENDENTE')
            """,
            (aporte.id,),
        )

        # Calcula o total confirmado da campanha.
        total = conn.execute(
            """
            SELECT COALESCE(SUM(valor), 0)
            FROM aporte
            WHERE campanha_id = ? AND status = 'CONFIRMADO'
            """,
            (campanha_id,),
        ).fetchone()[0]

        confirmado_em = datetime.now(UTC)

        evento_aporte = AporteConfirmado(
            aporte_id=aporte.id,
            campanha_id=campanha_id,
            investidor_id=investidor_id,
            valor=valor_centavos,
            confirmado_em=confirmado_em,
        )

        evento_total = TotalArrecadadoAtualizado(
            campanha_id=campanha_id,
            valor_acumulado=int(total),
        )

        # Registra AporteConfirmado na outbox.
        add(
            conn,
            OutboxEvent(
                agregado_id=aporte.id,
                tipo_evento=APORTE_CONFIRMADO,
                payload=evento_aporte.model_dump(
                    mode="json",
                    by_alias=True,
                ),
                correlation_id=correlation_id,
            ),
        )

        # Registra TotalArrecadadoAtualizado na outbox.
        add(
            conn,
            OutboxEvent(
                agregado_id=campanha_id,
                tipo_evento=TOTAL_ARRECADADO_ATUALIZADO,
                payload=evento_total.model_dump(
                    mode="json",
                    by_alias=True,
                ),
                correlation_id=correlation_id,
            ),
        )

        resposta: dict[str, str | int] = {
            "aporteId": aporte.id,
            "campanhaId": campanha_id,
            "investidorId": investidor_id,
            "valor": valor_centavos,
            "status": aporte.status.value,
        }

        resultado = ResultadoAporte(
            status_http=201,
            resposta=resposta,
        )

        # Persiste a resposta para garantir idempotência.
        conn.execute(
            """
            INSERT INTO aporte_requisicao (
                idempotency_key,
                aporte_id,
                campanha_id,
                investidor_id,
                valor,
                status_http,
                resposta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                idempotency_key,
                aporte.id,
                campanha_id,
                investidor_id,
                valor_centavos,
                resultado.status_http,
                json.dumps(resposta, ensure_ascii=False),
            ),
        )

        return resultado

    return transaction(operacao, "aportes", data_dir)


def rejeitar_aporte(
    *,
    idempotency_key: str,
    campanha_id: str,
    investidor_id: str,
    valor_centavos: int,
    data_dir: str | Path = "data",
) -> ResultadoAporte:
    """Registra aporte rejeitado por indisponibilidade de Campanhas.

    A rejeição e a resposta idempotente são salvas na mesma
    transação. Nenhum evento financeiro ou registro de
    pendência de Custódia é criado.
    """

    if not idempotency_key.strip():
        raise ValueError("Idempotency-Key é obrigatória")

    valor = Valor(valor_centavos)

    def operacao(conn: sqlite3.Connection) -> ResultadoAporte:
        existente = conn.execute(
            """
            SELECT campanha_id, investidor_id, valor,
                   status_http, resposta_json
            FROM aporte_requisicao
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()

        if existente is not None:
            (
                campanha_anterior,
                investidor_anterior,
                valor_anterior,
                status_http,
                resposta_anterior,
            ) = existente

            if (
                campanha_anterior != campanha_id
                or investidor_anterior != investidor_id
                or valor_anterior != valor_centavos
            ):
                raise ChaveIdempotenciaConflitante(
                    "Idempotency-Key já utilizada com dados diferentes"
                )

            return ResultadoAporte(
                status_http=int(status_http),
                resposta=json.loads(resposta_anterior),
            )

        # Cria o agregado e aplica a transição para REJEITADO.
        aporte = Aporte(
            id=str(uuid4()),
            campanha_id=campanha_id,
            investidor_id=investidor_id,
            valor=valor,
        ).rejeitar()

        # Persiste a rejeição sem criar eventos na outbox.
        salvar_aporte_na_transacao(conn, aporte)

        resposta: dict[str, str | int] = {
            "aporteId": aporte.id,
            "campanhaId": campanha_id,
            "investidorId": investidor_id,
            "valor": valor_centavos,
            "status": aporte.status.value,
        }

        resultado = ResultadoAporte(
            status_http=503,
            resposta=resposta,
        )

        # Salva a resposta para que a mesma chave não crie
        # outro aporte após a recuperação de Campanhas.
        conn.execute(
            """
            INSERT INTO aporte_requisicao (
                idempotency_key,
                aporte_id,
                campanha_id,
                investidor_id,
                valor,
                status_http,
                resposta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                idempotency_key,
                aporte.id,
                campanha_id,
                investidor_id,
                valor_centavos,
                resultado.status_http,
                json.dumps(resposta, ensure_ascii=False),
            ),
        )

        return resultado

    return transaction(operacao, "aportes", data_dir)


def consultar_resultado_anterior(
    *,
    idempotency_key: str,
    campanha_id: str,
    investidor_id: str,
    valor_centavos: int,
    data_dir: str | Path = "data",
) -> ResultadoAporte | None:
    """Recupera uma resposta anterior sem criar outro aporte."""

    if not idempotency_key.strip():
        raise ValueError("Idempotency-Key é obrigatória")

    def operacao(conn: sqlite3.Connection) -> ResultadoAporte | None:
        existente = conn.execute(
            """
            SELECT campanha_id, investidor_id, valor,
                   status_http, resposta_json
            FROM aporte_requisicao
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()

        if existente is None:
            return None

        (
            campanha_anterior,
            investidor_anterior,
            valor_anterior,
            status_http,
            resposta_json,
        ) = existente

        if (
            campanha_anterior != campanha_id
            or investidor_anterior != investidor_id
            or valor_anterior != valor_centavos
        ):
            raise ChaveIdempotenciaConflitante("Idempotency-Key já utilizada com dados diferentes")

        resposta: dict[str, str | int] = json.loads(resposta_json)

        return ResultadoAporte(
            status_http=int(status_http),
            resposta=resposta,
        )

    return transaction(operacao, "aportes", data_dir)
