import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_commits as cc  # noqa: E402


@pytest.mark.parametrize(
    "msg",
    [
        "feat(aportes): validar Idempotency-Key no POST /aportes (#21)",
        "fix(custodia): impedir retenção duplicada (#23)",
        "chore: atualizar dependências (#1)",
        "feat(broker)!: mudar formato do envelope (#5)",
        "docs(docs): atualizar README (#36)",
        "Merge branch 'main' into feature/21-x",
        "fixup! feat(aportes): x (#21)",
    ],
)
def test_commits_validos(msg):
    assert cc.check_subject(msg) == []


@pytest.mark.parametrize(
    "msg",
    [
        "adicionei idempotência",
        "feat(aportes): sem número da issue",
        "feat(aportes): número no lugar errado (#21) e mais texto",
        "feature(aportes): tipo inexistente (#21)",
        "feat(inexistente): escopo fora da lista (#21)",
        "feat(aportes):sem espaço (#21)",
        "feat(aportes): issue zero (#0)",
        "feat(aportes): " + "x" * 100 + " (#1)",
        "",
    ],
)
def test_commits_invalidos(msg):
    assert cc.check_subject(msg) != []


@pytest.mark.parametrize(
    "name", ["feature/21-aportes-idempotencia", "fix/7-bug", "main", "docs/36-readme"]
)
def test_branches_validas(name):
    assert cc.check_branch(name) == []


@pytest.mark.parametrize(
    "name", ["feature/aportes", "feature/21", "Feature/21-x", "feature/21-Aportes", "minha-branch"]
)
def test_branches_invalidas(name):
    assert cc.check_branch(name) != []


def test_hook_le_primeira_linha_nao_comentada(tmp_path):
    f = tmp_path / "msg"
    f.write_text("# comentário\nfeat(aportes): ok (#2)\n\ncorpo\n")
    assert cc.main(["--file", str(f)]) == 0
    f.write_text("mensagem ruim\n")
    assert cc.main(["--file", str(f)]) == 1
