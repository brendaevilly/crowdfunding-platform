# gateway

API Gateway: roteia, valida JWT, rate limit.

Porta padrão: **3000** (definida em `services.json`).

Regras: depende só de `packages/*` e nunca importa código de outro app (ver `docs/adr/ADR-001-arquitetura-microsservicos-local.md`).
