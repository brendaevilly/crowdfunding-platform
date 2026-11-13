# Microsserviços locais (sem Docker, sem nuvem)

Objetivo: ter **microsserviços de verdade** (processos independentes, banco próprio, comunicação só por HTTP/eventos) rodando na máquina de desenvolvimento com um único comando, sem Docker e sem AWS. A infraestrutura da nuvem (RDS, DynamoDB, SQS, K8s) prevista nos documentos fica para uma etapa posterior; aqui cada peça tem um substituto local equivalente.

> Stack: Python 3.12+, FastAPI + uvicorn, httpx, pydantic v2, SQLite (`sqlite3` da stdlib), pytest, ruff, uv (workspaces). Estilo: domínio com funções puras e estruturas imutáveis (`@dataclass(frozen=True)`), efeitos nas bordas.

## 1. Processos

| Processo | Porta | Papel |
|---|---|---|
| `gateway` | 3000 | API Gateway: roteia, valida JWT, rate limit |
| `broker` | 3010 | Message broker local (substitui SQS/SNS/RabbitMQ) |
| `identidade` | 3001 | Contas (Supporting) + KYC (Generic) |
| `campanhas` | 3002 | Gestão de Campanhas (Core) |
| `aportes` | 3003 | Aportes (Core) |
| `custodia_retornos` | 3004 | Custódia (Core) + Participação e Retornos (Supporting) |
| `notificacao` | 3005 | Notificação (Generic) |

São **5 microsserviços de negócio** (como no DDD Estratégico, Seção 2) + 2 processos de infraestrutura (gateway e broker). Cada serviço é um processo Python separado (uvicorn), com `pyproject.toml` próprio, sem importar código de outro serviço. O que é compartilhado fica só em `packages/` (utilitários e **contratos**).

## 2. Regras de isolamento (o que faz isso ser microsserviço)

1. **Database per Service**: cada serviço tem seu arquivo SQLite (`data/<servico>.db`). Nenhum serviço abre o arquivo de outro. Nos serviços agrupados, os bounded contexts ficam em tabelas com prefixo (`custodia_*`, `retornos_*`, `contas_*`, `kyc_*`) e em **módulos de código separados** (`src/modules/custodia`, `src/modules/retornos`), sem imports entre módulos, só via interface pública/evento interno.
2. **Sem FK entre contextos**; integridade por evento.
3. **Descoberta de serviços** por `services.json` na raiz (nome → URL base). Nenhuma URL fixa no código.
4. **Contratos versionados** em `packages/contracts` (modelos pydantic para eventos e endpoints síncronos). Todo serviço valida o que publica e o que recebe.
5. Serviços só se falam por: (a) **HTTP síncrono** direto (apenas Aportes → Campanhas, contrato 2.3) ou (b) **eventos via broker**.

## 3. Broker local (o coração da comunicação assíncrona)

Processo próprio, HTTP + SQLite (`data/broker.db`):

- `POST /subscriptions` `{ service, topic, url }`: o serviço registra seus tópicos ao subir (idempotente).
- `POST /publish` `{ eventId, topic, payload, correlationId }`: grava a mensagem e cria uma entrega por assinante (**fan-out publish/subscribe**: `UsuarioCadastrado` vai para Campanhas e KYC).
- Um *dispatcher* interno faz `POST <url do assinante>/events` para cada entrega pendente. Resposta 2xx = ack. Qualquer outra coisa ou timeout = retry.
- **At-least-once** com **backoff exponencial** (ex.: 1s, 2s, 4s… até N tentativas). Esgotou → vai para a **DLQ** (`GET /dlq`, `POST /dlq/:id/replay`) e loga alerta destacado para eventos financeiros.
- Mensagens persistem em disco: se o broker ou o consumidor cair, nada se perde; ao voltar, a entrega continua.
- Ordem não é garantida (de propósito), então os consumidores devem tolerar reordenação (ex.: `valorAcumulado` monotônico).

## 4. Dentro de cada serviço (`packages/shared`)

- **Transactional Outbox**: o serviço grava `outbox_evento` na mesma transação SQLite do estado de negócio. Um *relay* (timer de ~500 ms) lê `PENDENTE`, publica no broker e marca `PUBLICADO` só após o ack do broker.
- **Idempotent Consumer**: tabela `evento_processado(chave UNIQUE)` consultada/gravada na mesma transação do efeito. Reentrega vira no-op. Chaves: `usuarioId`, `aporteId`, `campanhaId`, `(usuarioId, eventoOrigemId)`, como no DDD Tático.
- **Circuit Breaker + timeout** no cliente HTTP síncrono (Aportes → Campanhas), fail-safe: sem resposta = rejeita.
- **Bulkhead**: cada serviço é um processo, logo tem memória, conexões e event loop (asyncio) próprios; o isolamento vem de graça. Ainda assim, limite de concorrência por consumidor.
- **Correlation ID**: gerado no gateway, propagado em header HTTP e no envelope do evento, presente em todo log. Substitui o tracing distribuído da nuvem.

## 5. Gateway local

Único ponto de entrada (`:3000`). Rotas `/api/identidade/*`, `/api/campanhas/*`, `/api/aportes/*`, `/api/retornos/*`, `/api/notificacoes/*` viram proxy para o serviço via `services.json`. Valida JWT (emitido pela Identidade), injeta `x-user-id`/`x-user-perfil`, aplica rate limit simples em memória.

## 6. Orquestração sem Docker

`make dev` roda `scripts/dev.py`:
1. sobe `broker` e espera `/health`;
2. sobe os 5 serviços em paralelo (cada um registra suas subscriptions);
3. sobe o `gateway`;
4. mostra logs com prefixo colorido por serviço; Ctrl+C derruba tudo em ordem inversa.

Também: `python scripts/dev.py only aportes custodia_retornos` (sobe só alguns) e `python scripts/dev.py kill custodia_retornos` (para testar resiliência: derrubar um serviço e ver o broker reentregar quando voltar). É o substituto local do "falha parcial não compromete o todo" (RNF7).

## 7. Tempo (prazo das campanhas)

Custódia apura o encerramento. Para ser testável localmente, o relógio é uma dependência injetável (`Clock`), e em modo dev existe `POST /_dev/clock/advance` na Custódia para avançar o tempo sem esperar dias.

## 8. Ajustes necessários nos contratos (lacunas encontradas nos documentos)

Ao desenhar a implementação surgiram pontos que os `.tex` ainda não cobrem. Estão incluídos como tarefas na issue de contratos:

1. **`CampanhaPublicada` cruza contexto**: Custódia precisa de `campanhaId`, `meta` e `prazoFim` para abrir a `ContaCustodia` e agendar a apuração. O DDD Tático diz que o evento é só interno. Deve virar evento de contrato Campanhas → Custódia.
2. **Notificação precisa de destinatários**: `ResultadoCampanha` e `RetornoDistribuido` devem trazer `empreendedorId` / `investidorIds` (ou o investidor do retorno), senão Notificação não sabe quem avisar.
3. **Contrato de Notificação**: listar `RetornoDistribuido` no lugar de `CampanhaLiquidada` (já apontado na Seção 7 do DDD Tático).
4. **Bloqueio de usuário**: o DDD Tático diz que Campanhas/Aportes validam "via evento", mas não existe evento. Criar `UsuarioStatusAlterado`.
5. **Taxa da plataforma** (regra 5): definir onde é calculada. Proposta: na `LIBERACAO` da Custódia, via configuração, com o valor líquido no `CampanhaLiquidada`.
6. **`CampanhaLiquidada` só em sucesso**: na falha ocorrem `DEVOLUCAO`s e apenas `ResultadoCampanha`.
