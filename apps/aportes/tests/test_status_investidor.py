"""Testes de bloqueio e desbloqueio de investidores."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from aportes.repository import inicializar_banco
from aportes.status_investidor import (
    consumir_usuario_status_alterado,
    investidor_esta_bloqueado,
)
from shared.db import transaction


def publicar_status(
    data_dir: Path,
    status_anterior: str,
    status_novo: str,
    instante: datetime,
) -> None:
    """Publica um evento de alteração de status para os testes."""
    payload = {
        "usuarioId": "investidor-1",
        "statusAnterior": status_anterior,
        "statusNovo": status_novo,
        "alteradoEm": instante.isoformat(),
    }

    transaction(
        lambda conn: consumir_usuario_status_alterado(conn, payload),
        "aportes",
        data_dir,
    )


def test_investidor_bloqueado(tmp_path: Path) -> None:
    """Verifica se um investidor bloqueado é identificado corretamente."""
    inicializar_banco(tmp_path)

    publicar_status(
        tmp_path,
        "ATIVO",
        "BLOQUEADO",
        datetime.now(UTC),
    )

    assert investidor_esta_bloqueado("investidor-1", tmp_path)


def test_investidor_desbloqueado(tmp_path: Path) -> None:
    """Verifica se o desbloqueio atualiza o estado do investidor."""
    inicializar_banco(tmp_path)
    agora = datetime.now(UTC)

    publicar_status(tmp_path, "ATIVO", "BLOQUEADO", agora)
    publicar_status(
        tmp_path,
        "BLOQUEADO",
        "ATIVO",
        agora + timedelta(seconds=1),
    )

    assert not investidor_esta_bloqueado("investidor-1", tmp_path)


def test_evento_antigo_nao_sobrescreve_status_recente(tmp_path: Path) -> None:
    """Garante que eventos antigos não substituam um status mais recente."""
    inicializar_banco(tmp_path)
    agora = datetime.now(UTC)

    publicar_status(tmp_path, "ATIVO", "BLOQUEADO", agora)
    publicar_status(
        tmp_path,
        "BLOQUEADO",
        "ATIVO",
        agora - timedelta(seconds=1),
    )

    assert investidor_esta_bloqueado("investidor-1", tmp_path)


def test_evento_repetido_nao_altera_estado(tmp_path: Path) -> None:
    """Garante que o processamento repetido preserve o estado."""
    inicializar_banco(tmp_path)
    agora = datetime.now(UTC)

    publicar_status(tmp_path, "ATIVO", "BLOQUEADO", agora)
    publicar_status(tmp_path, "ATIVO", "BLOQUEADO", agora)

    assert investidor_esta_bloqueado("investidor-1", tmp_path)
