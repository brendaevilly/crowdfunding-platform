#!/usr/bin/env python3
"""Gera a documentação dos contratos a partir de packages/contracts (fonte única).

    python scripts/gen_contratos_doc.py          # escreve docs/contratos/*
    python scripts/gen_contratos_doc.py --check  # falha se os arquivos estão desatualizados

Saídas:
  docs/contratos/CATALOGO.md                  catálogo legível (GitHub)
  docs/contratos/contratos-comunicacao.tex    trecho LaTeX para colar nos documentos .tex
"""

from __future__ import annotations

import sys
import types
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Union, get_args, get_origin

from pydantic import AwareDatetime

from contracts import CAMPANHA_STATUS_PATH, CATALOGO, SCHEMA_VERSION_ATUAL, StatusCampanha
from contracts.base import Contrato

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "docs" / "contratos"

CORRECOES = (
    (
        "LC-01",
        "CampanhaPublicada vira contrato entre Campanhas e Custódia",
        "Custódia precisa de campanhaId, meta, prazoFim e empreendedorId para abrir a "
        "ContaCustodia e agendar a apuração.",
    ),
    (
        "LC-02",
        "Notificação recebe os destinatários",
        "ResultadoCampanha traz empreendedorId e investidorIds; RetornoDistribuido traz "
        "investidorId.",
    ),
    (
        "LC-03",
        "Contrato de Notificação lista RetornoDistribuido",
        "RetornoDistribuido substitui CampanhaLiquidada no contrato de Notificação.",
    ),
    (
        "LC-04",
        "Novo evento UsuarioStatusAlterado",
        "Campanhas e Aportes passam a saber do bloqueio/desbloqueio de usuário por evento.",
    ),
    (
        "LC-05",
        "Taxa da plataforma calculada na LIBERACAO da Custódia",
        "CampanhaLiquidada informa valorBruto, taxaPlataforma e valorLiquido "
        "(valorBruto = taxaPlataforma + valorLiquido).",
    ),
    (
        "LC-06",
        "CampanhaLiquidada só em sucesso",
        "Na falha ocorrem as DEVOLUCOES e apenas ResultadoCampanha é emitido.",
    ),
)


def _tipo(anotacao: Any) -> str:
    origem = get_origin(anotacao)
    if origem in (Union, types.UnionType):
        partes = [a for a in get_args(anotacao) if a is not type(None)]
        return f"{_tipo(partes[0])} (opcional)"
    if origem is tuple:
        return f"lista de {_tipo(get_args(anotacao)[0])}"
    if isinstance(anotacao, type) and issubclass(anotacao, Enum):
        return " \\| ".join(str(m.value) for m in anotacao)
    if anotacao is str:
        return "string"
    if anotacao is int:
        return "inteiro (centavos)"
    if anotacao is AwareDatetime or anotacao is datetime:
        return "data/hora UTC (ISO 8601)"
    return str(anotacao)


def _campos(modelo: type[Contrato]) -> list[tuple[str, str, bool]]:
    return [
        (info.alias or nome, _tipo(info.annotation), info.is_required())
        for nome, info in modelo.model_fields.items()
    ]


def gerar_markdown() -> str:
    linhas = [
        "# Catálogo de contratos",
        "",
        "> Gerado por `scripts/gen_contratos_doc.py` a partir de `packages/contracts`. "
        "**Não edite à mão**: altere o código e rode o script.",
        "",
        f"Envelope de todo evento (schemaVersion atual: **{SCHEMA_VERSION_ATUAL}**): "
        "`eventId`, `topic`, `schemaVersion`, `occurredAt`, `correlationId`, `payload`. "
        "Valores monetários em centavos (inteiros). JSON em camelCase.",
        "",
        "## Eventos",
        "",
    ]
    for spec in CATALOGO.values():
        linhas += [
            f"### {spec.payload.__name__} (`{spec.topico}`)",
            "",
            f"- **Produtor:** {spec.produtor}",
            f"- **Chave de idempotência:** `{spec.chave_idempotencia}`",
            "- **Consumidores:**",
            *[f"  - `{c}`: {efeito}" for c, efeito in spec.consumidores.items()],
            "",
            "| Campo | Tipo | Obrigatório |",
            "|---|---|---|",
            *[f"| `{n}` | {t} | {'sim' if r else 'não'} |" for n, t, r in _campos(spec.payload)],
            "",
        ]
    linhas += [
        "## Endpoint síncrono (Aportes → Campanhas)",
        "",
        f"`GET {CAMPANHA_STATUS_PATH.replace('{campanha_id}', ':id')}`",
        "",
        "| Campo | Tipo | Obrigatório |",
        "|---|---|---|",
        "| `campanhaId` | string | sim |",
        f"| `status` | {' \\| '.join(s.value for s in StatusCampanha)} | sim |",
        "",
        "Somente `PUBLICADA` aceita aportes. Sem resposta ou erro: o aporte é rejeitado "
        "(fail-safe).",
        "",
        "## Correções aplicadas (seção 8 de ARQUITETURA_LOCAL.md)",
        "",
        *[f"- **{i}** {t}. {d}" for i, t, d in CORRECOES],
        "",
    ]
    return "\n".join(linhas)


def _tex(texto: str) -> str:
    for a, b in (
        ("\\|", "|"),
        ("\\", "\\textbackslash{}"),
        ("_", "\\_"),
        ("&", "\\&"),
        ("%", "\\%"),
    ):
        texto = texto.replace(a, b)
    return texto.replace("|", "\\textbar{}")


def gerar_tex() -> str:
    out = [
        "% Gerado por scripts/gen_contratos_doc.py a partir de packages/contracts.",
        "% Cole as seções abaixo no documento de Contratos de Comunicação (e as correções no",
        "% DDD Tático). Não edite à mão: altere o código e rode o script.",
        "",
        "\\subsection{Catálogo de eventos}",
        f"Todo evento trafega em um envelope com \\texttt{{eventId}}, \\texttt{{topic}}, "
        f"\\texttt{{schemaVersion}} (atual: {SCHEMA_VERSION_ATUAL}), \\texttt{{occurredAt}}, "
        "\\texttt{correlationId} e \\texttt{payload}. Valores monetários em centavos.",
        "",
    ]
    for spec in CATALOGO.values():
        out += [
            f"\\subsubsection{{{_tex(spec.payload.__name__)}}}",
            "\\begin{itemize}",
            f"  \\item Tópico: \\texttt{{{_tex(spec.topico)}}}",
            f"  \\item Produtor: {_tex(spec.produtor)}",
            f"  \\item Chave de idempotência: \\texttt{{{_tex(spec.chave_idempotencia)}}}",
            "  \\item Consumidores:",
            "  \\begin{itemize}",
            *[f"    \\item \\texttt{{{_tex(c)}}}: {_tex(e)}" for c, e in spec.consumidores.items()],
            "  \\end{itemize}",
            "\\end{itemize}",
            "\\begin{tabular}{lll}",
            "\\hline",
            "Campo & Tipo & Obrigatório \\\\",
            "\\hline",
            *[
                f"\\texttt{{{_tex(n)}}} & {_tex(t)} & {'sim' if r else 'não'} \\\\"
                for n, t, r in _campos(spec.payload)
            ],
            "\\hline",
            "\\end{tabular}",
            "",
        ]
    out += [
        "\\subsection{Contrato síncrono Aportes $\\rightarrow$ Campanhas}",
        f"\\texttt{{GET {_tex(CAMPANHA_STATUS_PATH.replace('{campanha_id}', ':id'))}}} "
        "retorna \\texttt{campanhaId} e \\texttt{status} "
        f"({_tex(' | '.join(s.value for s in StatusCampanha))}). "
        "Somente \\texttt{PUBLICADA} aceita aportes.",
        "",
        "\\subsection{Correções aos contratos}",
        "\\begin{enumerate}",
        *[f"  \\item \\textbf{{{i}}}: {_tex(t)}. {_tex(d)}" for i, t, d in CORRECOES],
        "\\end{enumerate}",
        "",
    ]
    return "\n".join(out)


ARQUIVOS = {
    "CATALOGO.md": gerar_markdown,
    "contratos-comunicacao.tex": gerar_tex,
}


def main(argv: list[str]) -> int:
    checar = "--check" in argv[1:]
    desatualizados: list[str] = []
    for nome, gerar in ARQUIVOS.items():
        destino = SAIDA / nome
        conteudo = gerar()
        if checar:
            atual = destino.read_text(encoding="utf-8") if destino.exists() else None
            if atual != conteudo:
                desatualizados.append(f"docs/contratos/{nome}")
        else:
            SAIDA.mkdir(parents=True, exist_ok=True)
            destino.write_text(conteudo, encoding="utf-8", newline="\n")
            print(f"escrito: docs/contratos/{nome}")
    if desatualizados:
        print("Desatualizado(s): " + ", ".join(desatualizados), file=sys.stderr)
        print("Rode: python scripts/gen_contratos_doc.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
