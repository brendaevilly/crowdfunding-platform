from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.config import (
    ConfigError,
    Settings,
    find_services_file,
    load_services,
    service_port,
    service_url,
)

RAIZ = Path(__file__).resolve().parents[3]


def _arquivo(tmp_path: Path, conteudo: object) -> Path:
    p = tmp_path / "services.json"
    p.write_text(json.dumps(conteudo), encoding="utf-8")
    return p


def test_settings_padrao() -> None:
    s = Settings.from_env({})
    assert (s.log_level, s.host, s.http_timeout, s.services_file) == (
        "INFO",
        "127.0.0.1",
        5.0,
        None,
    )


def test_settings_le_ambiente() -> None:
    s = Settings.from_env(
        {
            "LOG_LEVEL": "debug",
            "SERVICE_HOST": "0.0.0.0",
            "HTTP_TIMEOUT_SECONDS": "2.5",
            "SERVICES_FILE": "x.json",
        }
    )
    assert s.log_level == "DEBUG"
    assert s.host == "0.0.0.0"
    assert s.http_timeout == 2.5
    assert s.services_file == Path("x.json")


@pytest.mark.parametrize("valor", ["abc", "0", "-1"])
def test_settings_timeout_invalido(valor: str) -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"HTTP_TIMEOUT_SECONDS": valor})


def test_service_url_e_port(tmp_path: Path) -> None:
    arq = _arquivo(tmp_path, {"campanhas": {"url": "http://127.0.0.1:3002/", "port": 3002}})
    assert service_url("campanhas", arq) == "http://127.0.0.1:3002"
    assert service_port("campanhas", arq) == 3002


def test_servico_desconhecido(tmp_path: Path) -> None:
    arq = _arquivo(tmp_path, {"a": {"url": "http://x:1", "port": 1}})
    with pytest.raises(ConfigError, match="não existe"):
        service_url("b", arq)


def test_entrada_invalida(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="inválida"):
        load_services(_arquivo(tmp_path, {"a": {"url": "http://x:1"}}))


def test_json_quebrado(tmp_path: Path) -> None:
    p = tmp_path / "services.json"
    p.write_text("{nao e json", encoding="utf-8")
    with pytest.raises(ConfigError, match="não foi possível ler"):
        load_services(p)


def test_services_file_via_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arq = _arquivo(tmp_path, {"a": {"url": "http://x:9", "port": 9}})
    monkeypatch.setenv("SERVICES_FILE", str(arq))
    assert service_url("a") == "http://x:9"


def test_services_file_via_env_inexistente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICES_FILE", str(tmp_path / "nao-existe.json"))
    with pytest.raises(ConfigError, match="não encontrado"):
        find_services_file()


def test_procura_services_json_subindo_pastas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SERVICES_FILE", raising=False)
    arq = _arquivo(tmp_path, {})
    fundo = tmp_path / "a" / "b"
    fundo.mkdir(parents=True)
    assert find_services_file(start=fundo) == arq


def test_services_json_do_repositorio_e_valido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERVICES_FILE", raising=False)
    servicos = load_services(RAIZ / "services.json")
    assert servicos["campanhas"].port == 3002
    assert servicos["campanhas"].url == "http://127.0.0.1:3002"
