#!/usr/bin/env python3
"""Valida convenções do projeto: commits, título de PR e nome de branch.

Formato de commit / título de PR (Conventional Commits + nº da issue no fim):

    <tipo>(<escopo>)[!]: <descrição> (#<issue>)

    feat(aportes): validar Idempotency-Key no POST /aportes (#21)

Uso:
    check_commits.py --file .git/COMMIT_EDITMSG      # hook commit-msg
    check_commits.py --message "feat(x): y (#1)"     # título de PR
    check_commits.py --range origin/main..HEAD       # todos os commits de um PR
    check_commits.py --branch feature/21-aportes-idempotencia
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

TIPOS = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
)
ESCOPOS = (
    "gateway",
    "broker",
    "identidade",
    "campanhas",
    "aportes",
    "custodia",
    "retornos",
    "notificacao",
    "shared",
    "contracts",
    "frontend",
    "e2e",
    "infra",
    "ci",
    "docs",
    "deps",
)
MAX_SUBJECT = 100

_COMMIT_RE = re.compile(
    rf"^(?P<tipo>{'|'.join(TIPOS)})"
    rf"(?:\((?P<escopo>{'|'.join(ESCOPOS)})\))?"
    r"(?P<breaking>!)?: (?P<desc>\S.*?) \(#(?P<issue>[1-9]\d*)\)$"
)
_BRANCH_RE = re.compile(r"^(feature|fix|chore|docs)/(?P<issue>[1-9]\d*)-[a-z0-9]+(?:-[a-z0-9]+)*$")
_IGNORADOS = ("Merge ", 'Revert "', "fixup! ", "squash! ")


def check_subject(subject: str) -> list[str]:
    """Retorna a lista de problemas (vazia = válido)."""
    subject = subject.strip()
    if subject.startswith(_IGNORADOS):
        return []
    if len(subject) > MAX_SUBJECT:
        return [f"assunto com {len(subject)} caracteres (máximo {MAX_SUBJECT})"]
    if not _COMMIT_RE.match(subject):
        return [
            "formato inválido. Esperado: <tipo>(<escopo>): <descrição> (#<issue>)",
            f"tipos: {', '.join(TIPOS)}",
            f"escopos: {', '.join(ESCOPOS)}",
        ]
    return []


def check_branch(name: str) -> list[str]:
    if name in ("main", "HEAD") or name.startswith("dependabot/"):
        return []
    if not _BRANCH_RE.match(name):
        return [
            f"branch '{name}' inválida. Esperado: feature/<issue>-<slug-em-minusculas> "
            "(também aceitos: fix/, chore/, docs/). Ex.: feature/21-aportes-idempotencia"
        ]
    return []


def _git_subjects(rev_range: str) -> list[tuple[str, str]]:
    out = subprocess.run(
        ["git", "log", "--no-merges", "--format=%h%x09%s", rev_range],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [tuple(line.split("\t", 1)) for line in out.splitlines() if line]  # type: ignore[misc]


def _report(label: str, problems: list[str]) -> int:
    if not problems:
        return 0
    print(f"ERRO em {label}:", file=sys.stderr)
    for p in problems:
        print(f"  - {p}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--file")
    g.add_argument("--message")
    g.add_argument("--range")
    g.add_argument("--branch")
    args = ap.parse_args(argv)

    if args.file:
        with open(args.file, encoding="utf-8") as f:
            linhas = [ln for ln in f.read().splitlines() if not ln.startswith("#")]
        subject = next((ln for ln in linhas if ln.strip()), "")
        return _report("mensagem de commit", check_subject(subject))
    if args.message is not None:
        return _report("título do PR", check_subject(args.message))
    if args.branch:
        return _report("nome da branch", check_branch(args.branch))
    falhas = 0
    commits = _git_subjects(args.range)
    for sha, subject in commits:
        falhas += _report(f"commit {sha} «{subject}»", check_subject(subject))
    if not commits:
        print("Nenhum commit para validar.")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
