# Plataforma de Crowdfunding

Plataforma de crowdfunding com custódia (escrow) dos aportes, construída como **microsserviços rodando localmente**, sem Docker. Modelagem completa (DDD estratégico/tático, contratos, dados, patterns) nos documentos do projeto; a arquitetura de execução local está em [`docs/ARQUITETURA_LOCAL.md`](docs/ARQUITETURA_LOCAL.md).

| Processo | Porta | | Processo | Porta |
|---|---|---|---|---|
| gateway | 3000 | | aportes | 3003 |
| identidade | 3001 | | custodia_retornos | 3004 |
| campanhas | 3002 | | notificacao | 3005 |
| broker | 3010 | | | |

## Pré-requisitos

- Python 3.12+ e [uv](https://docs.astral.sh/uv/)
- Git e `make`
- [GitHub CLI](https://cli.github.com/) (`gh`), só para criar issues e configurar o repositório

## Primeiros passos

```bash
git clone <repo> && cd <repo>
make install     # instala dependências e ativa os git hooks (obrigatório, uma vez)
make check       # lint + testes: deve passar antes de qualquer trabalho
make dev         # sobe todos os microsserviços (disponível após a issue F07)
```

Comandos do dia a dia:

| Comando | O que faz |
|---|---|
| `make check` | lint + testes. **Rode antes de abrir PR** (é o que o CI roda) |
| `make lint` / `make format` | verifica (ruff + mypy) / corrige estilo (ruff) |
| `make test` | testes unitários e de integração |
| `make e2e` | sobe tudo e roda os testes ponta a ponta |
| `make dev` | sobe todos os serviços |

## Estrutura do repositório

```
apps/                 um processo por serviço (cada um com pyproject.toml próprio)
  gateway  broker  identidade  campanhas  aportes  custodia_retornos  notificacao
packages/
  shared/             utilitários compartilhados (HTTP, banco, outbox)
  contracts/          contratos versionados (eventos e endpoints síncronos)
services.json         nome do serviço → URL/porta (nenhuma URL fixa no código)
.env.example          variáveis de ambiente (copie para .env)
```

Cada app depende **só** de `packages/*` e nunca importa outro app; `tests/test_arquitetura.py` verifica isso a cada `make check`.

## Fluxo de desenvolvimento

Todo trabalho nasce de uma **issue** e chega na `main` por **Pull Request**. Ninguém faz commit direto na `main`.

```
issue → branch feature/<nº>-slug → commits convencionais (#nº) → push → PR → CI verde + 1 aprovação → squash merge
```

1. **Escolha uma issue** do seu milestone, atribuída a você (labels `dev-a` / `dev-b`). Confira o campo "Depende de": issue com dependência aberta só começa com stubs/contratos combinados.
2. **Atualize a main e crie a branch**, com o número da issue:
   ```bash
   git switch main && git pull
   git switch -c feature/21-aportes-idempotencia
   ```
3. **Desenvolva em commits pequenos**, no padrão abaixo. Escreva o teste junto da funcionalidade.
4. **Rode `make check`** e faça `git push -u origin HEAD`.
5. **Abra o PR** para `main` (`gh pr create --fill` e ajuste). O título segue o padrão de commit e o corpo contém `Closes #21`.
6. **O CI roda sozinho.** Corrija o que falhar com novos commits na mesma branch.
7. **Revisão cruzada**: o outro dev revisa e aprova. Quem abriu o PR não aprova o próprio.
8. **Squash merge** (único permitido). A branch é apagada e a issue fecha sozinha.

Mantenha PRs pequenos (uma issue = um PR, idealmente < 400 linhas). Se a issue for grande, divida em sub-issues.

### Branches

`feature/<nº da issue>-<slug-em-minúsculas>`: ex.: `feature/21-aportes-idempotencia`.
Para correções e tarefas sem funcionalidade nova também valem `fix/`, `chore/` e `docs/`, sempre com o número da issue. O CI rejeita outros nomes.

### Commits (Conventional Commits + nº da issue)

```
<tipo>(<escopo>)[!]: <descrição no imperativo> (#<issue>)
```

Exemplos:

```
feat(aportes): exigir Idempotency-Key no POST /aportes (#21)
fix(custodia): impedir retenção duplicada na reentrega do evento (#23)
test(broker): cobrir envio para DLQ após esgotar tentativas (#5)
refactor(shared): extrair helper de transação (#4)
feat(contracts)!: incluir investidorIds em ResultadoCampanha (#8)
docs(docs): documentar fluxo de encerramento (#36)
```

- **Tipos:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`
- **Escopos:** `gateway`, `broker`, `identidade`, `campanhas`, `aportes`, `custodia`, `retornos`, `notificacao`, `shared`, `contracts`, `frontend`, `e2e`, `infra`, `ci`, `docs`, `deps` (opcional, mas recomendado)
- O `!` marca mudança que quebra contrato/compatibilidade.
- O **número da issue vai no fim do assunto**, entre `(#...)`. Assunto com até 100 caracteres.

O hook `commit-msg` (instalado por `make install`) recusa mensagens fora do padrão no momento do commit. O CI revalida **todos os commits** do PR, então não dá para driblar com `--no-verify`.

Para corrigir mensagens antigas da sua branch: `git rebase -i origin/main` e reescreva (`reword`). É seguro reescrever o histórico da *sua* branch de feature.

### Pull Requests

- **Título:** mesmo padrão do commit, ex.: `feat(aportes): fluxo completo de POST /aportes (#21)`. Como o merge é *squash*, o título vira a mensagem do commit na `main`.
- **Corpo:** use o template; precisa de `Closes #<issue>` (ou `Refs #<issue>` se o PR for só parte da issue).
- Marque o PR como *draft* enquanto estiver em andamento, para o outro dev saber que ainda não precisa revisar.
- Responda a todos os comentários antes do merge.

## CI (GitHub Actions)

Workflow em [`.github/workflows/ci.yml`](.github/workflows/ci.yml), disparado em todo PR para `main` e em todo push na `main`:

| Job | Verifica |
|---|---|
| **Convenções** | nome da branch, título do PR, todos os commits e `Closes #N` no corpo |
| **Lint** | `ruff check` e `ruff format --check` |
| **Testes** | `pytest -m "not e2e"` com cobertura (unitário + integração com broker real) |
| **E2E** | sobe os microsserviços e roda `pytest e2e` (ativa quando `e2e/` existir) |
| **CI OK** | agrega os anteriores; é o **único check obrigatório** da `main` |

Reproduza localmente o que o CI roda: `make check` (+ `make e2e`). Se passa na sua máquina e falha no CI, confira versões (`uv sync` limpo) e dependência de ordem/horário nos testes.

### Configuração única do repositório

Depois de criar o repo e fazer o primeiro push, um dos devs (admin) roda:

```bash
scripts/setup_github.sh OWNER/REPO
```

Isso deixa somente *squash merge* (título do PR como mensagem), apaga a branch após o merge e protege a `main`: PR obrigatório, 1 aprovação, branch atualizada com a `main` e o check **CI OK** verde. Atenção: proteção de branch em repositório *privado* exige plano pago do GitHub; sem ela, o fluxo funciona por acordo, mas nada impede um push direto.

## Testes

| Camada | Onde | O que testa |
|---|---|---|
| Domínio | `apps/<servico>/tests/unit` | agregados, VOs, invariantes. Funções puras, sem I/O |
| Integração | `apps/<servico>/tests/integration` | banco SQLite real, outbox, consumidores idempotentes, broker real em processo de teste |
| Contrato | `packages/contracts/tests` | produtores e consumidores respeitam os schemas de eventos |
| E2E | `e2e/` | fluxo completo pelo gateway; falhas e resiliência. Marcados com `@pytest.mark.e2e` |

Regras: funcionalidade nova sem teste não é aprovada. Todo consumidor de evento precisa de teste de **reentrega** (mesmo evento 2×, efeito 1×).

## Regras de arquitetura (o CI e a revisão cobram)

- Nenhum import entre `apps/*`. O que for comum vai para `packages/shared` ou `packages/contracts`.
- Cada serviço só abre o **seu** banco (`data/<servico>.db`). Nunca o de outro.
- Serviços só se comunicam por **evento via broker** ou pela única chamada síncrona prevista (Aportes → Campanhas).
- Eventos e payloads mudam **primeiro** em `packages/contracts`.
- Escrita de estado + evento sempre na mesma transação (outbox). Todo consumidor é idempotente.
- Domínio em funções puras e estruturas imutáveis; banco e HTTP ficam nas bordas.

## Issues e divisão do trabalho

As issues foram criadas pelo script `create_issues.py` (`python3 create_issues.py --repo OWNER/REPO --dev-a <user> --dev-b <user>`, entregue junto deste kit). Cada uma já traz tarefas, critérios de aceite, dependências, milestone (`M0` a `M4`) e tamanho (`size:S/M/L`).

Labels: responsável (`dev-a`/`dev-b`), **área** (`area:backend`, `area:frontend`, `area:devops`, `area:qa`, `area:docs`), serviço (`aportes`, `campanhas`, `gateway`…) e tamanho. Para ver tudo de uma área: `gh issue list --label area:frontend`.

- **Dev A:** plataforma (broker, outbox, resiliência) e núcleo financeiro (Aportes, Custódia, Retornos), mais E2E.
- **Dev B:** gateway, Identidade/KYC, Campanhas, Notificação, frontend, contratos, observabilidade e docs.

Ao começar uma issue, mova-a para *In progress* (ou comente); se descobrir trabalho novo, abra outra issue em vez de crescer o PR.

## Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| Commit recusado pelo hook | Assunto fora do padrão; veja os exemplos acima. Sem hook? Rode `make install` |
| CI falha em "Convenções" | Rebase interativo e `reword` nos commits; título do PR e branch também são validados |
| `git push` recusado pelo hook | Nome da branch fora de `feature/<nº>-slug` (`git branch -m novo-nome`) ou lint falhando (`make format`) |
| Porta já em uso ao rodar `make dev` | Sobrou processo de uma execução anterior; encerre-o ou use `python scripts/dev.py kill <serviço>` |
| Branch desatualizada no PR | `git fetch && git rebase origin/main && git push --force-with-lease` |
