#!/usr/bin/env python3
"""Rastreamento distribuído local por Correlation ID.

Junta logs estruturados e eventos de todos os microsserviços em ordem cronológica
para reconstruir a execução de Sagas coreografadas (ex.: encerramento de campanha,
aportes, cadastro e notificações).

Uso:
    python scripts/trace.py <correlationId>
    python scripts/trace.py <correlationId> --json
    python scripts/trace.py <correlationId> --logs-dir ./logs
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent

CORES_SERVICOS = {
    "gateway": "36",  # ciano
    "identidade": "32",  # verde
    "campanhas": "33",  # amarelo
    "aportes": "35",  # magenta
    "custodia_retornos": "34",  # azul
    "broker": "96",  # ciano claro
    "notificacao": "92",  # verde claro
}
RESET = "\033[0m"


def normalizar_timestamp(valor: str | None) -> datetime:
    """Converte diferentes formatos de data/hora ISO ou SQLite para datetime UTC."""
    if not valor:
        return datetime.min.replace(tzinfo=UTC)

    valor = valor.strip()
    if valor.endswith("Z"):
        valor = valor[:-1] + "+00:00"

    # Formato ISO padrão
    try:
        return datetime.fromisoformat(valor).astimezone(UTC)
    except ValueError:
        pass

    # Formato SQLite YYYY-MM-DD HH:MM:SS
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(valor, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue

    return datetime.min.replace(tzinfo=UTC)


def coletar_de_logs(logs_dir: Path, correlation_id: str) -> list[dict[str, Any]]:
    """Lê todos os arquivos .log e filtra entradas com o correlationId especificado."""
    entradas: list[dict[str, Any]] = []

    if not logs_dir.is_dir():
        return entradas

    for arquivo_log in sorted(logs_dir.glob("*.log")):
        servico_default = arquivo_log.stem

        try:
            conteudo = arquivo_log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for linha in conteudo.splitlines():
            linha = linha.strip()
            if not linha or correlation_id not in linha:
                continue

            # Tenta ler como JSON estruturado
            try:
                dado = json.loads(linha)
                if isinstance(dado, dict):
                    cid = dado.get("correlationId") or dado.get("correlation_id")
                    if cid == correlation_id or correlation_id in json.dumps(dado):
                        entradas.append(
                            {
                                "ts": dado.get("ts") or datetime.now(UTC).isoformat(),
                                "service": dado.get("service") or servico_default,
                                "level": dado.get("level", "INFO"),
                                "logger": dado.get("logger", ""),
                                "message": dado.get("message", ""),
                                "extra": {
                                    k: v
                                    for k, v in dado.items()
                                    if k
                                    not in (
                                        "ts",
                                        "service",
                                        "level",
                                        "logger",
                                        "message",
                                        "correlationId",
                                        "correlation_id",
                                    )
                                },
                                "source": "log",
                            }
                        )
                        continue
            except json.JSONDecodeError:
                pass

            # Fallback para linha texto pura que contenha o correlation_id
            entradas.append(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "service": servico_default,
                    "level": "INFO",
                    "logger": servico_default,
                    "message": linha,
                    "extra": {},
                    "source": "log_text",
                }
            )

    return entradas


def coletar_do_banco(data_dir: Path, correlation_id: str) -> list[dict[str, Any]]:
    """Coleta eventos e entregas do broker e outbox relacionados ao correlationId."""
    entradas: list[dict[str, Any]] = []

    if not data_dir.is_dir():
        return entradas

    # 1. Eventos do broker
    broker_db = data_dir / "broker.db"
    if broker_db.is_file():
        try:
            with closing(sqlite3.connect(broker_db)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT id, event_id, topic, correlation_id, created_at, payload
                    FROM broker_events
                    WHERE correlation_id = ?
                    ORDER BY id
                    """,
                    (correlation_id,),
                ).fetchall()

                for row in rows:
                    entradas.append(
                        {
                            "ts": row["created_at"],
                            "service": "broker",
                            "level": "INFO",
                            "logger": "broker.events",
                            "message": (
                                f"Evento '{row['topic']}' ({row['event_id']}) registrado no broker"
                            ),
                            "extra": {
                                "eventId": row["event_id"],
                                "topic": row["topic"],
                            },
                            "source": "broker",
                        }
                    )

                deliveries = conn.execute(
                    """
                    SELECT d.id, d.status, d.attempts, d.last_error, d.created_at, d.delivered_at,
                           e.topic, e.event_id, s.service, s.url
                    FROM broker_deliveries d
                    JOIN broker_events e ON e.id = d.event_id
                    JOIN broker_subscriptions s ON s.id = d.subscription_id
                    WHERE e.correlation_id = ?
                    ORDER BY d.id
                    """,
                    (correlation_id,),
                ).fetchall()

                for d in deliveries:
                    status_desc = d["status"]
                    horario = d["delivered_at"] or d["created_at"]
                    msg = (
                        f"Entrega do evento '{d['topic']}' para '{d['service']}' "
                        f"({d['url']}): status={status_desc} (tentativas={d['attempts']})"
                    )
                    if d["last_error"]:
                        msg += f" erro={d['last_error']}"

                    entradas.append(
                        {
                            "ts": horario,
                            "service": "broker",
                            "level": "INFO" if d["status"] == "delivered" else "WARN",
                            "logger": "broker.dispatcher",
                            "message": msg,
                            "extra": {
                                "deliveryId": d["id"],
                                "targetService": d["service"],
                                "status": d["status"],
                            },
                            "source": "broker_delivery",
                        }
                    )
        except sqlite3.Error:
            pass

    # 2. Outbox dos serviços
    for db_path in sorted(data_dir.glob("*.db")):
        if db_path.name == "broker.db":
            continue

        nome_servico = db_path.stem
        try:
            with closing(sqlite3.connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                # Verifica se a tabela outbox_evento existe
                tem_outbox = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='outbox_evento'"
                ).fetchone()

                if not tem_outbox:
                    continue

                rows = conn.execute(
                    """
                    SELECT outbox_id, agregado_id, tipo_evento, payload,
                           status, created_at, published_at
                    FROM outbox_evento
                    WHERE payload LIKE ?
                    ORDER BY outbox_id
                    """,
                    (f"%{correlation_id}%",),
                ).fetchall()

                for row in rows:
                    entradas.append(
                        {
                            "ts": row["created_at"],
                            "service": nome_servico,
                            "level": "INFO",
                            "logger": f"{nome_servico}.outbox",
                            "message": (
                                f"Outbox: evento '{row['tipo_evento']}' registrado "
                                f"para agregado '{row['agregado_id']}' (status={row['status']})"
                            ),
                            "extra": {
                                "outboxId": row["outbox_id"],
                                "tipo": row["tipo_evento"],
                                "status": row["status"],
                            },
                            "source": "outbox",
                        }
                    )
        except sqlite3.Error:
            continue

    return entradas


def formatar_linha_texto(
    e: dict[str, Any],
    usar_cor: bool = True,
    largura_servico: int = 15,
) -> str:
    """Formata uma entrada de log/evento em uma linha legível de console."""
    ts_dt = normalizar_timestamp(e["ts"])
    ts_str = ts_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    servico = e["service"]
    level = e["level"]
    msg = e["message"]

    extra_str = ""
    if e.get("extra"):
        detalhes = [
            f"{k}={v}"
            for k, v in e["extra"].items()
            if k not in ("eventId", "topic") and v is not None
        ]
        if detalhes:
            extra_str = f" [{', '.join(detalhes)}]"

    if not usar_cor:
        return f"[{ts_str}] [{servico:<{largura_servico}}] {level:<5} | {msg}{extra_str}"

    cor_servico = CORES_SERVICOS.get(servico, "37")
    cor_level = {
        "INFO": "\033[32m",
        "WARN": "\033[33m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;31m",
    }.get(level.upper(), "")

    prefixo_srv = f"\033[{cor_servico}m{servico:<{largura_servico}}{RESET}"
    prefixo_lvl = f"{cor_level}{level:<5}{RESET}"

    return f"\033[90m[{ts_str}]\033[0m [{prefixo_srv}] {prefixo_lvl} | {msg}{extra_str}"


def rastrear(
    correlation_id: str,
    logs_dir: Path = RAIZ / "logs",
    data_dir: Path = RAIZ / "data",
) -> list[dict[str, Any]]:
    """Reúne logs e eventos associados ao correlationId em ordem cronológica."""
    itens_log = coletar_de_logs(logs_dir, correlation_id)
    itens_banco = coletar_do_banco(data_dir, correlation_id)

    todos = itens_log + itens_banco

    # Ordena cronologicamente por timestamp
    todos.sort(key=lambda item: normalizar_timestamp(item["ts"]))
    return todos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconstrói a linha do tempo de uma operação/Saga por correlation-id."
    )
    parser.add_argument(
        "correlation_id",
        help="Correlation ID gerado na requisição HTTP ou evento.",
    )
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=RAIZ / "logs",
        help="Diretório de logs (padrão: ./logs)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=RAIZ / "data",
        help="Diretório de bancos SQLite (padrão: ./data)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="saida_json",
        help="Imprime o resultado em formato JSON.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Desativa cores ANSI.",
    )

    args = parser.parse_args(argv)

    registros = rastrear(
        args.correlation_id,
        logs_dir=args.logs_dir,
        data_dir=args.data_dir,
    )

    if args.saida_json:
        print(json.dumps(registros, indent=2, ensure_ascii=False, default=str))
        return 0

    usar_cor = sys.stdout.isatty() and not args.no_color and "NO_COLOR" not in os.environ

    print("=" * 80)
    print(f"TRACE DISTRIBUÍDO: {args.correlation_id} ({len(registros)} registros encontrados)")
    print("=" * 80)

    if not registros:
        print(f"Nenhum registro encontrado para o correlation-id '{args.correlation_id}'.")
        print(
            "Certifique-se de que os serviços estão rodando com "
            "scripts/dev.py ou que os dados existem."
        )
        print("=" * 80)
        return 0

    largura = max(len(r["service"]) for r in registros) if registros else 15
    for r in registros:
        print(formatar_linha_texto(r, usar_cor=usar_cor, largura_servico=largura))

    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
