from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import dev  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]


def test_ordem_cobre_exatamente_os_servicos_do_services_json() -> None:
    assert sorted(dev.ORDEM) == sorted(dev.carregar_servicos())


def test_carregar_servicos_le_portas() -> None:
    portas = dev.carregar_servicos(RAIZ / "services.json")
    assert portas["gateway"] == 3000
    assert portas["broker"] == 3010


def test_fases_completas_broker_negocio_gateway() -> None:
    fases = dev.planejar_fases(list(dev.ORDEM))
    assert fases[0] == ["broker"]
    assert fases[1] == list(dev.NEGOCIO)
    assert fases[2] == ["gateway"]


def test_fases_so_com_alguns_servicos() -> None:
    assert dev.planejar_fases(["custodia_retornos", "aportes"]) == [
        ["aportes", "custodia_retornos"]
    ]
    assert dev.planejar_fases(["gateway", "broker"]) == [["broker"], ["gateway"]]
    assert dev.planejar_fases([]) == []


def test_validar_nomes() -> None:
    conhecidos = {"aportes": 3003}
    assert dev.validar_nomes(["aportes"], conhecidos) == ["aportes"]
    with pytest.raises(ValueError, match="desconhecido"):
        dev.validar_nomes(["aportes", "xyz"], conhecidos)


def test_comando_usa_placeholder_sem_main(tmp_path: Path) -> None:
    cmd = dev.comando_servico("aportes", tmp_path)
    assert cmd[-3:] == ["-m", "shared.http.placeholder", "aportes"]


def test_comando_usa_main_do_app_quando_existe(tmp_path: Path) -> None:
    main = tmp_path / "apps" / "aportes" / "src" / "aportes" / "main.py"
    main.parent.mkdir(parents=True)
    main.write_text("", encoding="utf-8")
    assert dev.comando_servico("aportes", tmp_path)[-2:] == ["-m", "aportes.main"]


def test_backoff_dobra_ate_o_maximo() -> None:
    valores = [dev.BACKOFF_INICIAL]
    for _ in range(10):
        valores.append(dev.proximo_backoff(valores[-1]))
    assert valores[:4] == [1.0, 2.0, 4.0, 8.0]
    assert max(valores) == dev.BACKOFF_MAXIMO


def test_porta_livre_detecta_porta_ocupada() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        porta = int(s.getsockname()[1])
        assert dev.porta_livre(porta) is False
    assert dev.porta_livre(porta) is True


def test_prefixo_com_e_sem_cor() -> None:
    assert dev.prefixo("aportes", "36", 10, usar_cor=False) == "aportes    |"
    assert dev.prefixo("aportes", "36", 10, usar_cor=True) == "\033[36maportes    |\033[0m"


def test_health_ok_falha_sem_servidor() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = int(s.getsockname()[1])
    assert dev.health_ok(f"http://127.0.0.1:{porta}", timeout=0.3) is False


def test_url_servico(tmp_path: Path) -> None:
    arq = tmp_path / "services.json"
    arq.write_text(json.dumps({"a": {"url": "http://h:1/", "port": 1}}), encoding="utf-8")
    assert dev.url_servico("a", arq) == "http://h:1"


def test_parser_aceita_comandos() -> None:
    ap = dev.montar_parser()
    assert ap.parse_args(["up", "--restart"]).restart is True
    assert ap.parse_args(["only", "aportes", "campanhas"]).servicos == ["aportes", "campanhas"]
    assert ap.parse_args(["kill", "aportes"]).servico == "aportes"
    assert ap.parse_args(["start", "aportes"]).cmd == "start"
