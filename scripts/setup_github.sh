#!/usr/bin/env bash
# Configura o repositório: só squash merge, título do PR vira commit, branch apagada após merge,
# e proteção da main (PR + 1 aprovação + check "CI OK" obrigatório).
# Uso: scripts/setup_github.sh OWNER/REPO
# Requer: gh autenticado com permissão de admin no repositório.
# Obs.: proteção de branch em repositório privado exige plano GitHub Pro/Team.
set -euo pipefail
REPO="${1:?uso: $0 OWNER/REPO}"

gh api -X PATCH "repos/$REPO" \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
  -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=BLANK \
  -F delete_branch_on_merge=true >/dev/null
echo "Merge: somente squash, título do PR como mensagem."

gh api -X PUT "repos/$REPO/branches/main/protection" --input - >/dev/null <<JSON
{
  "required_status_checks": { "strict": true, "contexts": ["CI OK"] },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
echo "Proteção da main aplicada (PR + 1 aprovação + CI OK)."
