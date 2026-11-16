"""A documentação em docs/contratos precisa refletir os contratos reais."""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "scripts"))
import gen_contratos_doc as gen  # noqa: E402


def test_docs_gerados_estao_atualizados() -> None:
    for nome, gerar in gen.ARQUIVOS.items():
        arquivo = RAIZ / "docs" / "contratos" / nome
        assert arquivo.exists(), f"rode: python scripts/gen_contratos_doc.py ({nome} não existe)"
        assert arquivo.read_text(encoding="utf-8") == gerar(), (
            f"docs/contratos/{nome} desatualizado: rode python scripts/gen_contratos_doc.py"
        )


def test_catalogo_md_menciona_todos_os_eventos_e_as_6_correcoes() -> None:
    md = gen.gerar_markdown()
    for nome in (
        "UsuarioCadastrado",
        "UsuarioStatusAlterado",
        "IdentidadeVerificada",
        "CampanhaPublicada",
        "TotalArrecadadoAtualizado",
        "AporteConfirmado",
        "CampanhaLiquidada",
        "ResultadoCampanha",
        "RetornoDistribuido",
    ):
        assert f"### {nome}" in md
    for lc in range(1, 7):
        assert f"LC-0{lc}" in md
