# ADR-001 — Arquitetura de microsserviços local

- **Status:** Proposto — aguardando revisão e aprovação de Emanuelly e Brenda
- **Data:** 2026-11-13
- **Issue:** #4 — [Infra] ADR-001: arquitetura de microsserviços local
- **Dependência:** #3 — Scaffold do monorepo e convenções
- **Referência normativa:** [`../ARQUITETURA_LOCAL.md`](../ARQUITETURA_LOCAL.md)
- **Contratos:** #10 — Contratos: eventos e endpoints síncronos tipados

## Contexto

A plataforma de crowdfunding precisa preservar limites de contexto e propriedades de confiabilidade financeira, mas ser executável em desenvolvimento sem Docker, AWS ou distribuição em máquinas distintas. O diagrama de implantação em nuvem é uma visão futura; esta decisão trata apenas do ambiente local. A proposta e o README estabelecem que a comunicação deve ser por HTTP/eventos e que cada serviço mantém seus próprios dados.

## Decisão

Adotar **cinco microsserviços de negócio como processos Python independentes**, mais um gateway e um broker local, executados na mesma máquina. Stack: Python 3.12+, FastAPI, Uvicorn, httpx, Pydantic v2, SQLite com `sqlite3`, pytest, ruff e `uv` workspaces. Preferir funções puras e `@dataclass(frozen=True)` no domínio; isolar I/O nas bordas.

### Processos e portas

| Processo | Porta | Responsabilidade |
|---|---:|---|
| `gateway` | 3000 | Entrada única, proxy, JWT e rate limiting |
| `identidade` | 3001 | Contas e KYC |
| `campanhas` | 3002 | Campanhas |
| `aportes` | 3003 | Aportes |
| `custodia_retornos` | 3004 | Custódia e Participação/Retornos, em módulos isolados |
| `notificacao` | 3005 | Notificações |
| `broker` | 3010 | Entrega assíncrona de eventos |

### Isolamento e dados

1. **É proibido qualquer import entre `apps/*`**. Código reutilizável fica apenas em `packages/shared` e contratos versionados em `packages/contracts`.
2. Cada serviço é dono exclusivo de `data/<servico>.db`; nenhum serviço abre o SQLite de outro. O broker usa `data/broker.db`.
3. Contextos agrupados no mesmo processo permanecem separados por módulos (`src/modules/custodia`, `src/modules/retornos`; analogamente Contas/KYC) e por prefixos de tabelas (`custodia_*`, `retornos_*`, `contas_*`, `kyc_*`). Sem imports diretos entre módulos: interação via interface pública ou evento interno.
4. Não há chaves estrangeiras entre contextos. Referências externas são identificadores, e a consistência entre serviços é mantida por eventos.
5. A descoberta de endereços ocorre por `services.json`, sem URLs fixas no código.
6. A única comunicação HTTP síncrona entre serviços de negócio é **Aportes → Campanhas**, conforme contrato 2.3. Demais interações usam o broker. O gateway expõe rotas `/api/identidade/*`, `/api/campanhas/*`, `/api/aportes/*`, `/api/retornos/*` e `/api/notificacoes/*`.

### Eventos, resiliência e observabilidade

- Broker HTTP + SQLite: `POST /subscriptions` registra assinaturas idempotentes; `POST /publish` persiste evento e cria entregas para cada assinante; dispatcher envia `POST /events` ao consumidor.
- Entrega **at-least-once**, sem garantia de ordem. Resposta 2xx confirma; falhas geram retry com backoff exponencial e, após esgotar tentativas, DLQ com consulta e replay. Eventos financeiros geram alerta destacado.
- **Transactional outbox:** estado de negócio e `outbox_evento` são gravados na mesma transação SQLite; relay periódico publica e só marca `PUBLICADO` após ack do broker.
- **Consumidor idempotente:** registrar chave única em `evento_processado` na mesma transação do efeito; reentregas não repetem efeitos. A chave específica depende do contrato do evento.
- HTTP síncrono usa timeout e circuit breaker; indisponibilidade de Campanhas impede confirmação de aporte (fail-safe). Cada processo tem isolamento de recursos; consumidores limitam concorrência.
- Gateway valida JWT, injeta `x-user-id`/`x-user-perfil` e aplica rate limit simples. `correlationId` é propagado em requisições, eventos e logs.

### Execução e tempo

`make dev` aciona `scripts/dev.py`: inicia broker e aguarda `/health`, inicia os cinco serviços, depois gateway; apresenta logs identificados e encerra processos com Ctrl+C. Comandos auxiliares: `python scripts/dev.py only aportes custodia_retornos` e `python scripts/dev.py kill custodia_retornos` para ensaios de falha. Custódia recebe `Clock` injetável; em desenvolvimento, `POST /_dev/clock/advance` avança o relógio simulado.

## Seis lacunas de contrato e decisões propostas

As seis lacunas abaixo foram extraídas da seção 8 de `ARQUITETURA_LOCAL.md`. São **propostas sujeitas à aprovação da dupla e à formalização na issue de contratos**, não contratos já implementados.

| ID | Lacuna | Decisão proposta / encaminhamento |
|---|---|---|
| LC-01 | `CampanhaPublicada` descrito como interno, mas Custódia precisa conhecer a campanha | Publicar contrato entre Campanhas e Custódia com `campanhaId`, `meta`, `prazoFim` e `empreendedorId`. |
| LC-02 | Notificação não tem identificação dos destinatários | Incluir `empreendedorId` e `investidorIds` em `ResultadoCampanha` e `investidorId` em `RetornoDistribuido`. |
| LC-03 | Contrato de Notificação lista evento inadequado | Substituir `CampanhaLiquidada` por `RetornoDistribuido` no contrato de Notificação. |
| LC-04 | Bloqueio de usuário depende de evento não definido | Criar `UsuarioStatusAlterado` para Campanhas/Aportes consumirem. |
| LC-05 | Local do cálculo da taxa da plataforma não está definido | Calcular taxa configurável na `LIBERACAO` em Custódia; `CampanhaLiquidada` informa valor líquido. |
| LC-06 | Emissão de `CampanhaLiquidada` em falha não está explicitada | Emitir `CampanhaLiquidada` somente no sucesso; na falha registrar `DEVOLUCAO` e emitir apenas `ResultadoCampanha`. |

**Rastreabilidade:** LC-01 a LC-06 são encaminhadas à [issue de contratos #10](https://github.com/brendaevilly/crowdfunding-platform/issues/10); alterações de schema devem ocorrer primeiro em `packages/contracts` e ter testes de contrato.

## Consequências e trade-offs

- **Benefícios:** desenvolvimento sem infraestrutura de nuvem, isolamento de processos e dados, testes reproduzíveis de falha, contratos explícitos e proteção contra eventos duplicados.
- **Custos:** necessidade de gerenciar múltiplos processos, broker e relay; consistência entre serviços é eventual; SQLite limita paralelismo de escrita; eventos podem chegar fora de ordem e repetidos.
- **Limite:** esta ADR não aprova a implantação AWS/EKS nem substitui o detalhamento dos contratos.

## Validação e aceite

- [ ] Revisado por Emanuelly
- [ ] Revisado e aprovado por Brenda
- [ ] Issue #3 concluída ou dependência resolvida com a dupla
- [ ] LC-01 a LC-06 referenciadas na [issue de contratos #10](https://github.com/brendaevilly/crowdfunding-platform/issues/10)
- [ ] Verificada ausência de imports entre `apps/*` durante implementação e revisão
- [ ] `make check` e CI verdes quando a estrutura do monorepo estiver disponível
- [ ] PR para `main` com `Closes #4` e aprovação cruzada

## Referências

- [`docs/ARQUITETURA_LOCAL.md`](../ARQUITETURA_LOCAL.md), seções 1–8.
- `README.md`, fluxo de desenvolvimento, CI e regras de arquitetura.
- [Issue #10 — contratos tipados](https://github.com/brendaevilly/crowdfunding-platform/issues/10) (implementação dos schemas e atualização dos `.tex`).
- Issue #4 e dependência #3.
