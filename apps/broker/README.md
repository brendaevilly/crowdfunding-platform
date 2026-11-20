# broker

Message broker local (publish/subscribe, retry, DLQ).

Porta padrão: **3010** (definida em `services.json`).

Regras: depende só de `packages/*` e nunca importa código de outro app (ver `docs/adr/ADR-001-arquitetura-microsservicos-local.md`).

## Endpoints

| Método | Caminho | Descrição |
|---|---|---|
| `POST` | `/publish` | Publica evento com roteamento para assinantes |
| `POST` | `/subscriptions` | Registra assinatura de serviço em um tópico |
| `GET` | `/stats` | Estatísticas de entrega agrupadas por tópico |
| `GET` | `/dlq` | Lista mensagens que esgotaram tentativas (Dead Letter Queue) |
| `POST` | `/dlq/:id/replay` | Reenfileira mensagem da DLQ para novo processamento |
| `GET` | `/painel` | Painel de controle visual (HTML) ou dados (JSON) com eventos recentes, entregas pendentes e DLQ |
| `GET` | `/painel/dados` | Dados do painel exclusivamente em JSON |
| `GET` | `/` | Redirecionamento automático para `/painel` quando acessado via navegador |
