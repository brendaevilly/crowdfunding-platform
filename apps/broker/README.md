# broker

Message broker local (publish/subscribe, retry, DLQ).

Porta padrão: **3010** (definida em `services.json`).

Regras: depende só de `packages/*` e nunca importa código de outro app (ver `docs/adr/ADR-001-arquitetura-microsservicos-local.md`).
