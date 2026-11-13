## O que muda
<!-- 1-3 linhas: o que este PR entrega e por quê. -->

Closes #<número da issue>

## Como testar
<!-- Comandos/passos. Ex.: `make test`, `make dev` + chamada em /api/aportes -->

## Checklist
- [ ] Título do PR no formato `tipo(escopo): descrição (#issue)`
- [ ] Branch `feature/<issue>-<slug>` e commits no padrão Conventional Commits
- [ ] Testes adicionados/atualizados (domínio, integração ou contrato)
- [ ] `make check` passa localmente
- [ ] Contratos (`packages/contracts`) e documentação atualizados, se mudaram
- [ ] Sem import entre `apps/*` e sem acesso ao banco de outro serviço
