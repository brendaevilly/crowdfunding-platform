# shared

Utilitários compartilhados pelos serviços. Nunca importam código de `apps/*`.

## shared.http

```python
from pydantic import BaseModel
from shared.http import create_app, run, AppError, ServiceClient

app = create_app("aportes")  # logging JSON, /health, x-correlation-id, erros padronizados


class Entrada(BaseModel):
    valor: int


@app.post("/aportes")
async def criar(e: Entrada) -> Entrada:
    if e.valor <= 0:
        raise AppError(422, "valor_invalido", "Valor deve ser positivo.")
    return e


if __name__ == "__main__":
    run(app, "aportes")  # porta vem de services.json (ou env PORT)
```

- **Correlation ID**: o middleware lê `x-correlation-id` (gera um se faltar), coloca no contexto, devolve no response e inclui em todo log (`correlationId`).
- **Erros**: sempre `{"error": {"code", "message", "details", "correlationId"}}` (validação 422, `AppError`, 404/405 e 500 sem vazar detalhes).
- **Cliente**: `ServiceClient("campanhas")` resolve a URL em `services.json`, aplica timeout (`timeout=` ou `HTTP_TIMEOUT_SECONDS`, padrão 5s) e propaga o correlation-id atual.
- **Config** (`shared.config`): `service_url("campanhas")`, `service_port(...)`; variáveis `SERVICES_FILE`, `SERVICE_HOST`, `LOG_LEVEL`, `HTTP_TIMEOUT_SECONDS`, `PORT`.
- **Exemplo**: `uv run python -m shared.http.example` e abra <http://127.0.0.1:3099/health>.
