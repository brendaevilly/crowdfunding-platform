# notificacao

Microsserviço de **Notificação** (Generic Subdomain / Contexto Folha / Conformist).

- **Porta padrão:** `3005` (definida em `services.json`).
- **Banco de dados:** SQLite exclusivo em `data/notificacao.db`.
- **Regras arquiteturais:** depende unicamente de `packages/*` (`contracts` e `shared`) e nunca importa código de outros microsserviços (ADR-001).

---

## 1. Responsabilidade e Contexto

O microsserviço de Notificação é um serviço folha que atua em regime de melhor esforço (*best-effort*), sem impactos transacionais nos agregados de negócio das etapas anteriores (Identidade, Campanhas, Aportes, Custódia).

Suas principais atribuições são:
1. Consumir eventos de interesse via mensageria assíncrona.
2. Despachar a mensagem através de um canal simulado de comunicação (e-mail, SMS, push).
3. Persistir a notificação na tabela `notificacao` com chave de unicidade `(usuario_id, evento_origem_id)`.
4. Disponibilizar endpoint seguro para consulta das notificações do usuário autenticado.

---

## 2. Eventos Consumidos

| Tópico | Contrato | Destinatários Notificados | Idempotência (`evento_origem_id`) |
|---|---|---|---|
| `aporte.confirmado` | `AporteConfirmado` | Investidor (`investidorId`) | `aporteId` |
| `campanha.resultado` | `ResultadoCampanha` | Empreendedor (`empreendedorId`) e cada Investidor (`investidorIds`) | `{campanhaId}:resultado` |
| `retorno.distribuido` | `RetornoDistribuido` | Investidor (`investidorId`) | `retornoId` |
| `identidade.verificada` | `IdentidadeVerificada` | Usuário (`usuarioId`) | `{usuarioId}:identidade-verificada` |

---

## 3. Canal Simulado e Resiliência a Falhas

- **Simulação com Retentativas Locais:**
  - O componente `CanalNotificacao` realiza tentativas internas locais antes de concluir o status de envio.
  - Se o canal responder com sucesso, o registro é salvo com `status_envio = "ENVIADA"` e `enviado_em` preenchido.
  - Se o canal falhar após as tentativas (ou simulação de falha ativada via `NOTIFICACAO_SIMULAR_FALHA=true`), o registro é salvo com `status_envio = "FALHA"`.
- **Garantia de Não-Bloqueio do Broker:**
  - Erros no canal externo **nunca** lançam exceções para o handler de mensageria.
  - Dessa forma, falhas transitórias do canal não provocam loops infinitos de retentativa nem acúmulo desnecessário na DLQ do broker.
- **Idempotência por Chave Composta:**
  - A restrição `UNIQUE(usuario_id, evento_origem_id)` garante que reentregas de um mesmo evento não gerem notificações duplicadas nem reexecutem o envio pelo canal.

---

## 4. Endpoints HTTP da API

| Método | Caminho | Descrição | Autenticação | Status Sucesso |
|---|---|---|---|---|
| `GET` | `/notificacoes` | Lista todas as notificações do usuário autenticado (ordenadas da mais recente para a mais antiga) | `X-User-ID` ou `Authorization: Bearer <token>` | `200 OK` |
| `POST` | `/notificacoes/{id}/lida` | Marca a notificação como lida | `X-User-ID` ou `Authorization: Bearer <token>` | `200 OK` |

---

## 5. Expiração e TTL de Notificações (#31)

Substituto local para o recurso de TTL do DynamoDB:

- **Job Periódico de Limpeza (`run_ttl_cleaner`):**
  - Executa em background durante o ciclo de vida da aplicação.
  - Remove automaticamente registros da tabela `notificacao` mais antigos que o tempo de retenção configurado.
  - A remoção de notificações antigas não afeta a tabela de controle de mensageria (`evento_processado`), garantindo que a idempotência de eventos recentes permaneça intacta.
- **Configurações via Variáveis de Ambiente:**
  - `NOTIFICACAO_TTL_DIAS`: período de retenção em dias (padrão: `30`).
  - `NOTIFICACAO_TTL_INTERVALO_SEGUNDOS`: intervalo entre ciclos de varredura em segundos (padrão: `3600.0`).
  - `NOTIFICACAO_TTL_ENABLED`: habilita ou desabilita a execução da thread de limpeza (padrão: `true`, desabilitada em testes).

---

## 6. Testes

```bash
# Executar suíte de testes de notificação:
uv run python -m pytest apps/notificacao/tests -v

# Validações estáticas:
uv run python -m ruff check apps/notificacao
uv run python -m mypy apps/notificacao
```
