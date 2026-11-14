"""Regras do ADR-001: isolamento entre apps e dependências do workspace."""

from __future__ import annotations

import ast
import importlib
import json
import re
import tomllib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
APPS = sorted(p.name for p in (RAIZ / "apps").iterdir() if (p / "pyproject.toml").exists())
PACOTES = sorted(p.name for p in (RAIZ / "packages").iterdir() if (p / "pyproject.toml").exists())

APPS_ESPERADOS = [
    "aportes",
    "broker",
    "campanhas",
    "custodia_retornos",
    "gateway",
    "identidade",
    "notificacao",
]
PACOTES_ESPERADOS = ["contracts", "shared"]


def _pyproject(membro: Path) -> dict[str, object]:
    return tomllib.loads((membro / "pyproject.toml").read_text(encoding="utf-8"))


def _nome_dependencia(requisito: str) -> str:
    return re.split(r"[\s<>=!~;\[(]", requisito, maxsplit=1)[0].lower().replace("_", "-")


def _imports(arquivo: Path) -> set[str]:
    raizes: set[str] = set()
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            raizes.update(a.name.split(".")[0] for a in no.names)
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            raizes.add(no.module.split(".")[0])
    return raizes


def test_membros_do_workspace_existem():
    assert APPS == APPS_ESPERADOS
    assert PACOTES == PACOTES_ESPERADOS


@pytest.mark.parametrize("app", APPS)
def test_app_declara_so_dependencias_de_packages(app):
    projeto = _pyproject(RAIZ / "apps" / app)["project"]
    assert isinstance(projeto, dict)
    permitidas = {f"crowdfunding-{p}" for p in PACOTES}
    declaradas = {_nome_dependencia(d) for d in projeto["dependencies"]}
    assert declaradas <= permitidas, f"{app} declara dependências fora de packages/*"


@pytest.mark.parametrize("app", APPS)
def test_app_nao_importa_outro_app(app):
    outros = set(APPS) - {app}
    for arquivo in (RAIZ / "apps" / app).rglob("*.py"):
        proibidos = _imports(arquivo) & outros
        assert not proibidos, f"{arquivo.relative_to(RAIZ)} importa outro app: {proibidos}"


@pytest.mark.parametrize("pacote", PACOTES)
def test_package_nao_importa_apps(pacote):
    for arquivo in (RAIZ / "packages" / pacote).rglob("*.py"):
        proibidos = _imports(arquivo) & set(APPS)
        assert not proibidos, f"{arquivo.relative_to(RAIZ)} importa app: {proibidos}"


@pytest.mark.parametrize("modulo", APPS + PACOTES)
def test_membro_e_importavel(modulo):
    assert importlib.import_module(modulo) is not None


def test_services_json_cobre_todos_os_apps_com_portas_unicas():
    servicos = json.loads((RAIZ / "services.json").read_text(encoding="utf-8"))
    assert sorted(servicos) == APPS_ESPERADOS
    portas = [s["port"] for s in servicos.values()]
    assert len(portas) == len(set(portas))
    for nome, info in servicos.items():
        assert info["url"].endswith(f":{info['port']}"), nome
