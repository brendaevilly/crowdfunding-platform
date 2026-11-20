"""Painel e endpoints de observabilidade do broker local.

Exibe eventos recentes, entregas pendentes e mensagens na DLQ em formato JSON ou HTML.
"""

from __future__ import annotations

import html
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from shared.db import migrate, open_db

router = APIRouter()

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def obter_dados_painel(data_dir: str | Path = "data") -> dict[str, Any]:
    """Coleta o resumo, eventos recentes, pendentes e DLQ do broker."""
    migrate("broker", MIGRATIONS_DIR, data_dir=data_dir)

    with closing(open_db("broker", data_dir)) as conn:
        # Sumário geral
        row_summary = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM broker_events) AS total_events,
                (
                    SELECT COUNT(*) FROM broker_deliveries
                    WHERE status IN ('pending', 'processing')
                ) AS pending_deliveries,
                (
                    SELECT COUNT(*) FROM broker_deliveries
                    WHERE status = 'delivered'
                ) AS delivered_deliveries,
                (
                    SELECT COUNT(*) FROM broker_deliveries
                    WHERE status = 'dlq'
                ) AS dlq_deliveries
            """
        ).fetchone()

        summary = {
            "totalEvents": row_summary[0] if row_summary else 0,
            "pendingDeliveries": row_summary[1] if row_summary else 0,
            "deliveredDeliveries": row_summary[2] if row_summary else 0,
            "dlqDeliveries": row_summary[3] if row_summary else 0,
        }

        # Eventos recentes (últimos 50)
        rows_events = conn.execute(
            """
            SELECT
                e.id,
                e.event_id,
                e.topic,
                e.correlation_id,
                e.created_at,
                COUNT(d.id) AS total_deliveries,
                COALESCE(
                    SUM(CASE WHEN d.status = 'delivered' THEN 1 ELSE 0 END), 0
                ) AS delivered_count,
                COALESCE(
                    SUM(CASE WHEN d.status IN ('pending', 'processing') THEN 1 ELSE 0 END), 0
                ) AS pending_count,
                COALESCE(
                    SUM(CASE WHEN d.status = 'dlq' THEN 1 ELSE 0 END), 0
                ) AS dlq_count
            FROM broker_events AS e
            LEFT JOIN broker_deliveries AS d ON d.event_id = e.id
            GROUP BY e.id
            ORDER BY e.id DESC
            LIMIT 50
            """
        ).fetchall()

        recent_events = [
            {
                "id": r[0],
                "eventId": r[1],
                "topic": r[2],
                "correlationId": r[3],
                "createdAt": r[4],
                "deliveries": {
                    "total": r[5],
                    "delivered": r[6],
                    "pending": r[7],
                    "dlq": r[8],
                },
            }
            for r in rows_events
        ]

        # Entregas pendentes ou em processamento
        rows_pending = conn.execute(
            """
            SELECT
                d.id,
                e.event_id,
                e.topic,
                e.correlation_id,
                s.service,
                s.url,
                d.status,
                d.attempts,
                d.next_attempt_at,
                d.created_at
            FROM broker_deliveries AS d
            JOIN broker_events AS e ON e.id = d.event_id
            JOIN broker_subscriptions AS s ON s.id = d.subscription_id
            WHERE d.status IN ('pending', 'processing')
            ORDER BY d.id ASC
            LIMIT 50
            """
        ).fetchall()

        pending_deliveries = [
            {
                "id": r[0],
                "eventId": r[1],
                "topic": r[2],
                "correlationId": r[3],
                "service": r[4],
                "url": r[5],
                "status": r[6],
                "attempts": r[7],
                "nextAttemptAt": r[8],
                "createdAt": r[9],
            }
            for r in rows_pending
        ]

        # Mensagens na DLQ
        rows_dlq = conn.execute(
            """
            SELECT
                d.id,
                e.event_id,
                e.topic,
                e.correlation_id,
                s.service,
                s.url,
                d.attempts,
                d.last_error,
                d.created_at
            FROM broker_deliveries AS d
            JOIN broker_events AS e ON e.id = d.event_id
            JOIN broker_subscriptions AS s ON s.id = d.subscription_id
            WHERE d.status = 'dlq'
            ORDER BY d.id DESC
            LIMIT 50
            """
        ).fetchall()

        dlq = [
            {
                "id": r[0],
                "eventId": r[1],
                "topic": r[2],
                "correlationId": r[3],
                "service": r[4],
                "url": r[5],
                "attempts": r[6],
                "lastError": r[7],
                "createdAt": r[8],
            }
            for r in rows_dlq
        ]

    return {
        "summary": summary,
        "recentEvents": recent_events,
        "pendingDeliveries": pending_deliveries,
        "dlq": dlq,
    }


def render_html_painel(dados: dict[str, Any]) -> str:
    """Gera visualização HTML responsiva para o painel do broker."""
    summary = dados["summary"]
    recentes = dados["recentEvents"]
    pendentes = dados["pendingDeliveries"]
    dlq = dados["dlq"]

    def _linha_evento(e: dict[str, Any]) -> str:
        d = e["deliveries"]
        status_badge = (
            f"<span class='badge badge-success'>{d['delivered']} entregue(s)</span>"
            if d["pending"] == 0 and d["dlq"] == 0
            else f"<span class='badge badge-warn'>{d['pending']} pendente(s)</span>"
        )
        if d["dlq"] > 0:
            status_badge += f" <span class='badge badge-danger'>{d['dlq']} na DLQ</span>"

        cid = html.escape(e["correlationId"] or "-")
        return f"""
        <tr>
            <td><strong>#{e["id"]}</strong></td>
            <td><code>{html.escape(e["eventId"])}</code></td>
            <td><span class="badge badge-info">{html.escape(e["topic"])}</span></td>
            <td><code>{cid}</code></td>
            <td>{html.escape(str(e["createdAt"]))}</td>
            <td>{status_badge}</td>
        </tr>
        """

    def _linha_pendente(p: dict[str, Any]) -> str:
        cid = html.escape(p["correlationId"] or "-")
        return f"""
        <tr>
            <td>#{p["id"]}</td>
            <td><code>{html.escape(p["eventId"])}</code></td>
            <td><span class="badge badge-info">{html.escape(p["topic"])}</span></td>
            <td><strong>{html.escape(p["service"])}</strong><br><small>{html.escape(p["url"])}</small></td>
            <td><span class="badge badge-warn">{html.escape(p["status"])}</span></td>
            <td>{p["attempts"]}</td>
            <td>{html.escape(str(p["nextAttemptAt"] or "Imediato"))}</td>
            <td><code>{cid}</code></td>
        </tr>
        """

    def _linha_dlq(item: dict[str, Any]) -> str:
        cid = html.escape(item["correlationId"] or "-")
        err = html.escape(str(item["lastError"] or "-"))
        return f"""
        <tr>
            <td>#{item["id"]}</td>
            <td><code>{html.escape(item["eventId"])}</code></td>
            <td><span class="badge badge-danger">{html.escape(item["topic"])}</span></td>
            <td><strong>{html.escape(item["service"])}</strong></td>
            <td>{item["attempts"]}</td>
            <td class="text-danger"><small>{err}</small></td>
            <td><code>{cid}</code></td>
            <td>
                <button class="btn btn-sm btn-replay"
                        onclick="replayDelivery({item["id"]})">Replay</button>
            </td>
        </tr>
        """

    msg_ev = "<tr><td colspan='6' class='text-muted'>Nenhum evento registrado ainda.</td></tr>"
    msg_pen = "<tr><td colspan='8' class='text-muted'>Nenhuma entrega pendente.</td></tr>"
    msg_dlq = "<tr><td colspan='8' class='text-muted'>Fila DLQ vazia.</td></tr>"

    linhas_eventos = "".join(_linha_evento(e) for e in recentes) or msg_ev
    linhas_pendentes = "".join(_linha_pendente(p) for p in pendentes) or msg_pen
    linhas_dlq = "".join(_linha_dlq(item) for item in dlq) or msg_dlq

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Broker Local — Painel de Observabilidade</title>
    <style>
        :root {{
            --bg: #0f172a;
            --surface: #1e293b;
            --surface-hover: #334155;
            --border: #334155;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --primary: #38bdf8;
            --success: #4ade80;
            --warn: #facc15;
            --danger: #f87171;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
            padding: 24px;
        }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }}
        h1 {{ font-size: 1.6rem; color: var(--primary); }}
        .header-actions {{ display: flex; gap: 12px; }}
        .btn {{
            background: var(--primary);
            color: #0f172a;
            font-weight: 600;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }}
        .btn:hover {{ opacity: 0.9; }}
        .btn-sm {{ padding: 4px 8px; font-size: 0.8rem; }}
        .btn-replay {{ background: var(--warn); }}
        .btn-json {{
            background: var(--surface);
            color: var(--text);
            border: 1px solid var(--border);
        }}
        .cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .card {{
            background: var(--surface);
            padding: 16px;
            border-radius: 8px;
            border: 1px solid var(--border);
        }}
        .card-title {{ font-size: 0.85rem; color: var(--text-muted); text-transform: uppercase; }}
        .card-value {{ font-size: 2rem; font-weight: bold; margin-top: 4px; }}
        .card-value.primary {{ color: var(--primary); }}
        .card-value.success {{ color: var(--success); }}
        .card-value.warn {{ color: var(--warn); }}
        .card-value.danger {{ color: var(--danger); }}
        .section {{
            background: var(--surface);
            border-radius: 8px;
            border: 1px solid var(--border);
            padding: 20px;
            margin-bottom: 24px;
        }}
        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }}
        .section-title {{ font-size: 1.15rem; font-weight: 600; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }}
        th, td {{
            text-align: left;
            padding: 10px 12px;
            border-bottom: 1px solid var(--border);
        }}
        th {{
            color: var(--text-muted);
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        tr:hover td {{ background: var(--surface-hover); }}
        code {{
            background: rgba(255, 255, 255, 0.08);
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.85em;
            color: var(--primary);
        }}
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge-info {{ background: #0369a1; color: #e0f2fe; }}
        .badge-success {{ background: #15803d; color: #dcfce7; }}
        .badge-warn {{ background: #a16207; color: #fef9c3; }}
        .badge-danger {{ background: #b91c1c; color: #fee2e2; }}
        .text-danger {{ color: var(--danger); }}
        .text-muted {{ color: var(--text-muted); text-align: center; padding: 20px 0; }}
    </style>
</head>
<body>
    <header>
        <div>
            <h1>Broker de Mensagens — Observabilidade</h1>
            <p style="color: var(--text-muted); font-size: 0.85rem;">
                Eventos assíncronos, entregas pendentes e DLQ
            </p>
        </div>
        <div class="header-actions">
            <a href="/painel/dados" class="btn btn-json" target="_blank">Ver JSON</a>
            <button class="btn" onclick="window.location.reload()">Atualizar</button>
        </div>
    </header>

    <div class="cards">
        <div class="card">
            <div class="card-title">Total de Eventos</div>
            <div class="card-value primary">{summary["totalEvents"]}</div>
        </div>
        <div class="card">
            <div class="card-title">Entregas Concluídas</div>
            <div class="card-value success">{summary["deliveredDeliveries"]}</div>
        </div>
        <div class="card">
            <div class="card-title">Entregas Pendentes</div>
            <div class="card-value warn">{summary["pendingDeliveries"]}</div>
        </div>
        <div class="card">
            <div class="card-title">Mensagens na DLQ</div>
            <div class="card-value danger">{summary["dlqDeliveries"]}</div>
        </div>
    </div>

    <div class="section">
        <div class="section-header">
            <div class="section-title">Eventos Recentes ({len(recentes)})</div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Event ID</th>
                    <th>Tópico</th>
                    <th>Correlation ID</th>
                    <th>Horário</th>
                    <th>Status Entregas</th>
                </tr>
            </thead>
            <tbody>
                {linhas_eventos}
            </tbody>
        </table>
    </div>

    <div class="section">
        <div class="section-header">
            <div class="section-title">Entregas Pendentes ({len(pendentes)})</div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Event ID</th>
                    <th>Tópico</th>
                    <th>Destino</th>
                    <th>Status</th>
                    <th>Tentativas</th>
                    <th>Próximo Envio</th>
                    <th>Correlation ID</th>
                </tr>
            </thead>
            <tbody>
                {linhas_pendentes}
            </tbody>
        </table>
    </div>

    <div class="section">
        <div class="section-header">
            <div class="section-title">Dead Letter Queue — DLQ ({len(dlq)})</div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Event ID</th>
                    <th>Tópico</th>
                    <th>Destino</th>
                    <th>Tentativas</th>
                    <th>Último Erro</th>
                    <th>Correlation ID</th>
                    <th>Ação</th>
                </tr>
            </thead>
            <tbody>
                {linhas_dlq}
            </tbody>
        </table>
    </div>

    <script>
        async function replayDelivery(id) {{
            if (!confirm(`Deseja reenviar a entrega #${{id}} da DLQ?`)) return;
            try {{
                const res = await fetch(`/dlq/${{id}}/replay`, {{ method: "POST" }});
                if (res.ok) {{
                    alert("Entrega reenfileirada com sucesso!");
                    window.location.reload();
                }} else {{
                    alert("Falha ao reenviar entrega.");
                }}
            }} catch (err) {{
                alert("Erro ao conectar com o broker: " + err);
            }}
        }}
    </script>
</body>
</html>
"""


@router.get("/painel")
def painel_broker(request: Request, format: str | None = None) -> Response:
    """Exibe painel de observabilidade em HTML ou JSON."""
    dados = obter_dados_painel()

    quer_html = format == "html" or (
        "text/html" in request.headers.get("accept", "") and format != "json"
    )

    if quer_html:
        return HTMLResponse(content=render_html_painel(dados))

    return Response(
        content=__import__("json").dumps(dados, ensure_ascii=False),
        media_type="application/json",
    )


@router.get("/painel/dados")
def painel_dados_json() -> dict[str, Any]:
    """Endpoint puramente JSON com os dados do painel."""
    return obter_dados_painel()
