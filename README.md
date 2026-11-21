# Plataforma de Crowdfunding

Plataforma de crowdfunding com custódia (*escrow*) dos aportes, construída como **microsserviços rodando localmente**, sem Docker e sem custos de nuvem durante o ciclo de desenvolvimento. Modelagem completa (DDD estratégico/tático, contratos, dados, patterns) nos documentos do projeto; a arquitetura de execução local está descrita em detalhe em [`docs/ARQUITETURA_LOCAL.md`](docs/ARQUITETURA_LOCAL.md).

| Processo | Porta | Papel Arquitetural |
|---|---|---|
| **gateway** | `3000` | API Gateway unificado, proxy reverso, validação JWT, rate limiting e interface web |
| **identidade** | `3001` | Gestão de contas, autenticação e verificação cadastral (KYC) |
| **campanhas** | `3002` | Criação, ciclo de vida, metas e moderação de campanhas |
| **aportes** | `3003` | Registro idempotente e validação de aportes com limites e KYC |
| **custodia_retornos** | `3004` | Conta de custódia (*escrow*), liquidação de campanhas, cálculo de cotas e distribuição de retornos |
| **notificacao** | `3005` | Envio e consulta de notificações de eventos para os usuários |
| **broker** | `3010` | Mensageria local orientada a eventos assíncronos (pub/sub, retry, DLQ e painel web) |

---

## Diagrama da Arquitetura Local

```mermaid
flowchart TD
    subgraph Cliente["Frontend e Clientes HTTP"]
        Browser["Navegador / SPA (Porta :3000)"]
    end

    subgraph Borda["Borda da Plataforma"]
        Gateway["Gateway Local (:3000)\nFastAPI Proxy • JWT • Rate Limit • Static UI"]
    end

    subgraph Servicos["Microsserviços de Negócio (Processos Independentes)"]
        Identidade["Identidade & KYC (:3001)"]
        Campanhas["Campanhas (:3002)"]
        Aportes["Aportes (:3003)"]
        Custodia["Custódia & Retornos (:3004)"]
        Notificacao["Notificação (:3005)"]
    end

    subgraph Dados["Isolamento Database-per-Service (SQLite)"]
        DB_Identidade[("data/identidade.db")]
        DB_Campanhas[("data/campanhas.db")]
        DB_Aportes[("data/aportes.db")]
        DB_Custodia[("data/custodia_retornos.db")]
        DB_Notificacao[("data/notificacao.db")]
        DB_Broker[("data/broker.db")]
    end

    subgraph Mensageria["Broker Local de Mensagens (:3010)"]
        BrokerPub["POST /publish"]
        BrokerDispatcher["Dispatcher com Backoff & Retries"]
        DLQ["Dead Letter Queue (DLQ)\nGET /dlq • Replay"]
    end

    Browser -->|HTTP / JSON| Gateway
    Gateway -->|/api/identidade| Identidade
    Gateway -->|/api/campanhas| Campanhas
    Gateway -->|/api/aportes| Aportes
    Gateway -->|/api/retornos| Custodia
    Gateway -->|/api/notificacoes| Notificacao

    Identidade --- DB_Identidade
    Campanhas --- DB_Campanhas
    Aportes --- DB_Aportes
    Custodia --- DB_Custodia
    Notificacao --- DB_Notificacao
    BrokerPub --- DB_Broker

    %% Comunicação Síncrona Específica
    Aportes -.->|HTTP Síncrono (Circuit Breaker)\nGET /campanhas/:id/status| Campanhas

    %% Publicação via Outbox
    Identidade ==>|Outbox Relay| BrokerPub
    Campanhas ==>|Outbox Relay| BrokerPub
    Aportes ==>|Outbox Relay| BrokerPub
    Custodia ==>|Outbox Relay| BrokerPub

    %% Entregas do Broker
    BrokerDispatcher -->|POST /events\nusuario.cadastrado| Campanhas
    BrokerDispatcher -->|POST /events\nidentidade.verificada| Aportes
    BrokerDispatcher -->|POST /events\ncampanha.publicada| Custodia
    BrokerDispatcher -->|POST /events\naporte.confirmado| Custodia
    BrokerDispatcher -->|POST /events\naporte.confirmado| Campanhas
    BrokerDispatcher -->|POST /events\ncampanha.resultado| Campanhas
    BrokerDispatcher -->|POST /events\ncampanha.resultado| Custodia
    BrokerDispatcher -->|POST /events\nnotificacoes| Notificacao
    BrokerDispatcher -->|Falhas Excedidas| DLQ
```

---

## Pré-requisitos

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** (gerenciador rápido de dependências e ambientes virtuais)
- **Git** e **Make** (no Linux/macOS) ou PowerShell (no Windows)
- **[GitHub CLI](https://cli.github.com/) (`gh`)** para criação de PRs e acompanhamento

---

## Primeiros Passos: Rodando o Sistema

Qualquer novo desenvolvedor consegue rodar o sistema e explorar a interface em poucos comandos:

```bash
# 1. Clonar o repositório
git clone https://github.com/brendaevilly/crowdfunding-platform.git
cd crowdfunding-platform

# 2. Instalar todas as dependências e ativar hooks do Git
make install
# (ou manualmente: uv sync --all-packages && git config core.hooksPath .githooks)

# 3. Subir todos os microsserviços locais (em um terminal)
make dev
# (ou: uv run python scripts/dev.py up)

# 4. Popular o banco com dados de demonstração (em outro terminal)
make seed
# (ou: uv run python scripts/seed_demo.py)
```

Abra no navegador:
- **Interface da Plataforma:** [http://127.0.0.1:3000](http://127.0.0.1:3000)
- **Painel do Broker & DLQ:** [http://127.0.0.1:3010/painel](http://127.0.0.1:3010/painel)
- **Health Agregado e Circuit Breakers:** [http://127.0.0.1:3000/health](http://127.0.0.1:3000/health)

### Credenciais de Demonstração (criadas por `make seed`)

Todos os usuários de teste usam a senha: `SenhaDemo1234!`

| Perfil | E-mail | Funcionalidades para Testar |
|---|---|---|
| **Administrador** | `admin@aporta.demo` | Moderação, aprovação de campanhas e visualização gerencial |
| **Empreendedor** | `empreendedora@aporta.demo` | Criação de campanhas, acompanhamento de captação e distribuição de retornos |
| **Investidor 1** | `investidor1@aporta.demo` | KYC aprovado, aporte de R$ 1.200,00 e recebimento de retornos |
| **Investidor 2** | `investidor2@aporta.demo` | KYC aprovado, aporte de R$ 800,00 e notificações |
| **Investidor 3** | `investidor3@aporta.demo` | KYC aprovado, aporte de R$ 500,00 e extrato financeiro |

---

## Comandos do Dia a Dia

| Comando | O que faz |
|---|---|
| `make dev` | Sobe o ecossistema completo de microsserviços (Ctrl+C encerra tudo sem órfãos) |
| `make seed` | Popula o sistema com usuários, campanhas aprovadas e aportes via Gateway |
| `make check` | Executa linters (`ruff`), checagem de tipos (`mypy`) e testes de unidade/integração |
| `make format` | Formata o código e corrige regras mecânicas via `ruff` |
| `make test` | Roda testes unitários, de arquitetura e integração (`pytest -m "not e2e"`) |
| `make e2e` | Executa os testes ponta a ponta (caminho feliz e testes de falha/resiliência) |
| `make contratos` | Regenera a documentação dos contratos e trecho LaTeX a partir de `packages/contracts` |

### Controle do Launcher Local (`scripts/dev.py`)

Com o `make dev` em execução em um terminal, você pode controlar os serviços individualmente por outro terminal:

```bash
python scripts/dev.py status             # Exibe o status de cada microsserviço
python scripts/dev.py kill custodia_retornos  # Derruba um serviço específico
python scripts/dev.py start custodia_retornos # Sobe o serviço novamente
```

---

## Testes e Garantia de Qualidade

A plataforma conta com uma pirâmide de testes abrangente:

| Camada | Localização | O que valida |
|---|---|---|
| **Domínio (Unitários)** | `apps/<servico>/tests/` | Regras puras de negócio, agregados, Value Objects, invariantes e cálculo de liquidação. |
| **Integração** | `tests/test_*_integration.py` | Transações SQLite reais, outbox relay, publicação no broker e consumo idempotente. |
| **Contratos** | `packages/contracts/tests/` | Validação bidirecional de produtores e consumidores contra schemas Pydantic v2. |
| **Arquitetura** | `tests/test_arquitetura.py` | Isolamento estrito entre apps (proíbe imports cruzados entre `apps/*`). |
| **E2E: Caminho Feliz** | `e2e/test_caminho_feliz.py` | Fluxo completo ponta a ponta: cadastro, KYC, criação, aprovação, aportes, relógio virtual, liquidação, cotas 100% e distribuição de retornos. |
| **E2E: Falhas & Resiliência** | `e2e/test_falhas_resiliencia.py` | RNF2, RNF7 e contratos sob falhas reais (meta não atingida, serviços caídos, reinício de broker e DLQ). |

### Cenários de Resiliência Testados (`e2e/test_falhas_resiliencia.py`)

| Cenário | Comportamento sob Falha | Garantia Auditada |
|---|---|---|
| **Meta não atingida** | Campanha expira sem arrecadar o total da meta | Liquidação apurada como `FALHA`, estorno/devolução integral de todos os aportes, taxa da plataforma zerada e `saldo_retido = 0`. |
| **Custódia fora durante aportes** | Serviço de Custódia é derrubado no meio dos aportes | Aportes continuam sendo aceitos pelo gateway; eventos acumulam no broker e são processados na volta da Custódia, **sem retenção duplicada**. |
| **Campanhas fora do ar** | Serviço de Campanhas é derrubado | Aportes são rejeitados com `503 Service Unavailable` (**Circuit Breaker** atuando); nenhuma retenção inconsistente é gravada na Custódia. |
| **Reinício abrupto do broker** | Broker morre e volta durante o fluxo de captação | **Zero perda de dados**: mensagens persistem na outbox dos serviços de origem e são reenviadas assim que o broker retorna. |
| **Evento envenenado (Poison Message)** | Payload inválido ou incompatível é publicado | Após atingir o limite de tentativas com erro `422`, o evento é isolado na **DLQ** (`/dlq`); a ação de `/replay` reprocessa a mensagem sem travar a fila. |

---

## Do Local para a Nuvem: Mapeamento de Arquitetura

A arquitetura foi projetada para que cada padrão aplicado localmente tenha correspondência direta e sem atrito com serviços gerenciados em provedores de nuvem (como AWS, GCP ou Azure):

| Componente Local | Equivalente em Produção / Nuvem | Motivação & Transição Arquitetural |
|---|---|---|
| **Broker Local HTTP (`:3010`)** | **Amazon SQS + SNS** ou **Apache Kafka / RabbitMQ gerenciado** | No ambiente local, o broker provê fan-out, entregas at-least-once com backoff e DLQ via SQLite. Na nuvem, adota-se o padrão SNS (fan-out topics) roteando para filas SQS dedicadas por serviço com Dead Letter Queues gerenciadas. |
| **Bancos SQLite Isolados (`data/<servico>.db`)** | **Amazon RDS PostgreSQL / Aurora** (para dados relacionais) e **Amazon DynamoDB** (para outbox/idempotência) | O princípio *Database-per-Service* permanece idêntico: cada microsserviço possui seu próprio schema/cluster isolado com credenciais exclusivas, réplicas de leitura e backups automatizados. |
| **Launcher de Processos (`scripts/dev.py`)** | **Kubernetes (EKS / GKE)** ou **AWS ECS / Google Cloud Run** | O gerenciamento local de ciclo de vida (`up`, `kill`, `start`, health check) traduz-se em contêineres OCI com *Deployments*, *Readiness/Liveness Probes*, auto-recuperação e escalabilidade horizontal automática (HPA). |
| **Gateway Local (`:3000`)** | **AWS API Gateway**, **Kong Gateway** ou **Ingress Controller (Envoy/Traefik)** | O roteamento por prefixo (`/api/*`), rate limiting e validação centralizada de tokens JWT passam a ser executados na camada de borda gerenciada da nuvem. |
| **Transactional Outbox Relay** | **Debezium (Change Data Capture - CDC)** ou **DynamoDB Streams + Lambda** | Localmente, o relay publica via timer em background. Na nuvem, adota-se CDC lendo os *write-ahead logs* (WAL) do banco para streaming no Kafka/EventBridge com latência próxima de zero e sem polling. |
| **Rastreamento (`scripts/trace.py`)** | **OpenTelemetry (OTel)** + **AWS X-Ray / Jaeger / Datadog** | O `x-correlation-id` propagado localmente mapeia-se no padrão W3C *TraceContext* (`traceparent`), gerando spans e gráficos de dependência distribuídos em tempo real. |

---

## Estrutura do Repositório

```
apps/                       # Microsserviços independentes (um processo cada)
  gateway/                  # Proxy de borda, rotas públicas e UI estática
  broker/                   # Motor pub/sub, dispatcher assíncrono e DLQ
  identidade/               # Contas de usuários, autenticação JWT e KYC
  campanhas/                # Agregado de campanhas, metas e moderação
  aportes/                  # Checkout, idempotência e limites de investimento
  custodia_retornos/        # Escrow, liquidação financeira, cotas e retornos
  notificacao/              # Notificações assíncronas por usuário
packages/                   # Bibliotecas compartilhadas (código comum)
  shared/                   # Utilitários de banco, outbox, HTTP e circuit breaker
  contracts/                # Schemas Pydantic v2 versionados de eventos e APIs
scripts/                    # Ferramentas operacionais e de desenvolvimento
  dev.py                    # Launcher e orquestrador dos microsserviços
  seed_demo.py              # Carga inicial com dados realistas de demonstração
  seed_admin.py             # Provisionamento do primeiro administrador
  trace.py                  # Rastreamento de Sagas ponta a ponta por correlationId
  gen_contratos_doc.py      # Gerador automático da documentação LaTeX dos contratos
e2e/                        # Testes End-to-End completos (pytest)
docs/                       # Modelagem DDD, diagramas e decisões arquiteturais (ADRs)
```

---

## Fluxo de Desenvolvimento e Contribuição

Todo o desenvolvimento segue o fluxo de branches curtas com integração contínua rigorosa:

1. **Branch dedicada:** `feature/<nº-issue>-<slug>` (ex.: `feature/38-readme-diagrama-seed-de-demonstracao`).
2. **Commits Convencionais:** `<tipo>(<escopo>): <descrição no imperativo> (#<issue>)`.
3. **Validação antes do Push:** `make check` (garante zero violações em `ruff`, `mypy` e testes de unidade).
4. **Pull Request:** Abrir para a branch `main` com `Closes #<issue>`. O merge é realizado via *Squash & Merge* após o CI verde e aprovação cruzada.
