"""Testes do rastreador distribuído local (scripts/trace.py).

Garante que é possível reconstruir a linha do tempo completa de uma Saga
(como o encerramento de campanha) através do correlation-id por um único comando.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from trace import formatar_linha_texto, main, rastrear  # noqa: E402


def test_coletar_de_logs(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    cid_alvo = "corr-saga-100"
    cid_outro = "corr-outro-200"

    (logs_dir / "gateway.log").write_text(
        json.dumps(
            {
                "ts": "2026-11-20T10:00:00.100+00:00",
                "service": "gateway",
                "level": "INFO",
                "logger": "gateway",
                "message": "request POST /api/campanhas/c1/status",
                "correlationId": cid_alvo,
                "status": 200,
            }
        )
        + "\n"
        + json.dumps(
            {
                "ts": "2026-11-20T10:00:01.000+00:00",
                "service": "gateway",
                "level": "INFO",
                "logger": "gateway",
                "message": "request GET /api/identidade/login",
                "correlationId": cid_outro,
                "status": 200,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    (logs_dir / "campanhas.log").write_text(
        json.dumps(
            {
                "ts": "2026-11-20T10:00:00.200+00:00",
                "service": "campanhas",
                "level": "INFO",
                "logger": "campanhas.api",
                "message": "Campanha c1 consultada",
                "correlationId": cid_alvo,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    resultado = rastrear(cid_alvo, logs_dir=logs_dir)
    assert len(resultado) == 2

    assert resultado[0]["service"] == "gateway"
    assert resultado[0]["extra"]["status"] == 200
    assert resultado[1]["service"] == "campanhas"
    assert resultado[1]["message"] == "Campanha c1 consultada"


def test_reconstruir_encerramento_campanha(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Critério: É possível reconstruir encerramento de campanha com um comando."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    cid_encerramento = "corr-encerramento-campanha-42"

    # 1. Gateway recebe requisição de moderação/encerramento
    (logs_dir / "gateway.log").write_text(
        json.dumps(
            {
                "ts": "2026-11-20T12:00:00.000+00:00",
                "service": "gateway",
                "level": "INFO",
                "logger": "gateway",
                "message": "request POST /api/campanhas/42/encerrar",
                "correlationId": cid_encerramento,
                "status": 200,
                "durationMs": 14.5,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # 2. Campanhas processa e grava na outbox
    (logs_dir / "campanhas.log").write_text(
        json.dumps(
            {
                "ts": "2026-11-20T12:00:00.020+00:00",
                "service": "campanhas",
                "level": "INFO",
                "logger": "campanhas.api",
                "message": "Campanha 42 transicionada para ENCERRADA com resultado SUCESSO",
                "correlationId": cid_encerramento,
            }
        )
        + "\n"
        + json.dumps(
            {
                "ts": "2026-11-20T12:00:00.035+00:00",
                "service": "campanhas",
                "level": "INFO",
                "logger": "campanhas.outbox",
                "message": "Outbox: evento ResultadoCampanha gravado",
                "correlationId": cid_encerramento,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # 3. Broker recebe publicação e entrega aos assinantes
    (logs_dir / "broker.log").write_text(
        json.dumps(
            {
                "ts": "2026-11-20T12:00:00.060+00:00",
                "service": "broker",
                "level": "INFO",
                "logger": "broker.publish",
                "message": "Publicado evento ResultadoCampanha para tópico ResultadoCampanha",
                "correlationId": cid_encerramento,
            }
        )
        + "\n"
        + json.dumps(
            {
                "ts": "2026-11-20T12:00:00.090+00:00",
                "service": "broker",
                "level": "INFO",
                "logger": "broker.dispatcher",
                "message": "Entrega do evento ResultadoCampanha para notificacao",
                "correlationId": cid_encerramento,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # 4. Notificação consome evento e envia e-mails simulados
    (logs_dir / "notificacao.log").write_text(
        json.dumps(
            {
                "ts": "2026-11-20T12:00:00.120+00:00",
                "service": "notificacao",
                "level": "INFO",
                "logger": "notificacao.consumidores",
                "message": ("Evento ResultadoCampanha recebido; notificando investidores"),
                "correlationId": cid_encerramento,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Executa o comando trace
    codigo = main(
        [
            cid_encerramento,
            "--logs-dir",
            str(logs_dir),
            "--no-color",
        ]
    )
    assert codigo == 0

    saida = capsys.readouterr().out
    assert "TRACE DISTRIBUÍDO: corr-encerramento-campanha-42" in saida
    assert "6 registros encontrados" in saida

    # Valida a ordem cronológica estrita na visualização
    pos_gateway = saida.find("gateway")
    pos_campanhas = saida.find("campanhas")
    pos_broker = saida.find("broker")
    pos_notificacao = saida.find("notificacao")

    assert pos_gateway < pos_campanhas < pos_broker < pos_notificacao


def test_trace_saida_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    cid = "corr-json-123"

    (logs_dir / "servico.log").write_text(
        json.dumps(
            {
                "ts": "2026-11-20T10:00:00.000Z",
                "service": "servico",
                "level": "INFO",
                "message": "teste json",
                "correlationId": cid,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    main([cid, "--logs-dir", str(logs_dir), "--json"])
    saida = capsys.readouterr().out
    dados = json.loads(saida)

    assert isinstance(dados, list)
    assert len(dados) == 1
    assert dados[0]["service"] == "servico"
    assert dados[0]["message"] == "teste json"


def test_trace_sem_registros(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    codigo = main(["corr-inexistente", "--logs-dir", str(logs_dir)])
    assert codigo == 0
    saida = capsys.readouterr().out
    assert "Nenhum registro encontrado" in saida


def test_formatar_linha_texto() -> None:
    linha = formatar_linha_texto(
        {
            "ts": "2026-11-20T10:00:00.123456+00:00",
            "service": "broker",
            "level": "INFO",
            "message": "evento entregue",
            "extra": {"attempts": 1},
        },
        usar_cor=False,
    )
    assert "[2026-11-20 10:00:00.123]" in linha
    assert "[broker         ]" in linha
    assert "INFO  | evento entregue [attempts=1]" in linha
