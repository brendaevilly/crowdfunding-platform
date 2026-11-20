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

## 5. Testes

```bash
# Executar suíte de testes de notificação:
uv run python -m pytest apps/notificacao/tests -v

# Validações estáticas:
uv run python -m ruff check apps/notificacao
uv run python -m mypy apps/notificacao
```
