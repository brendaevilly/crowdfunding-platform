# gateway

Ponto único de entrada (`:3000`): proxy por prefixo, JWT, rate limit e `/health` agregado.

## Rotas

`/api/<prefixo>/*` vira proxy para o serviço (URL em `services.json`). O gateway remove só o `/api`; cada serviço é dono do seu namespace:

| Público | Serviço | Chega ao serviço como |
|---|---|---|
| `/api/identidade/*` | `identidade` | `/identidade/*` |
| `/api/campanhas/*` | `campanhas` | `/campanhas/*` (ex.: `GET /campanhas/:id/status`) |
| `/api/aportes/*` | `aportes` | `/aportes/*` (ex.: `POST /aportes`) |
| `/api/retornos/*` | `custodia_retornos` | `/retornos/*` |
| `/api/notificacoes/*` | `notificacao` | `/notificacoes/*` |

Tabela de prefixos e rotas públicas: `src/gateway/rotas.py`. Rotas públicas (sem JWT): `POST /api/identidade/usuarios` (cadastro) e `POST /api/identidade/login`.

## Autenticação

`Authorization: Bearer <jwt>` (HS256, segredo em `JWT_SECRET`; a Identidade emite com `shared.auth.emitir_token`). O gateway valida, injeta `x-user-id` e `x-user-perfil` (perfil do contrato: `EMPREENDEDOR` ou `INVESTIDOR`) e **não repassa** o `Authorization`. `x-user-*` enviados pelo cliente são sempre descartados. Sem `JWT_SECRET`, usa um segredo de desenvolvimento e avisa no log.

## Respostas do gateway

| Status | `error.code` | Quando |
|---|---|---|
| 401 | `nao_autenticado` / `token_invalido` / `token_expirado` | rota protegida sem token válido |
| 404 | `rota_desconhecida` | prefixo inexistente |
| 413 | `corpo_grande_demais` | corpo acima de 1 MiB |
| 429 | `limite_excedido` | rate limit (header `Retry-After`) |
| 503 | `servico_indisponivel` | serviço de destino fora do ar |
| 504 | `servico_timeout` | serviço não respondeu a tempo |

Respostas dos serviços (inclusive 4xx/5xx) passam sem alteração. Todo erro leva `correlationId`; o gateway gera o `x-correlation-id` quando ausente e o propaga ao serviço.

## Rate limit

Em memória (token bucket): `RATE_LIMIT_REQUESTS` por `RATE_LIMIT_WINDOW_SECONDS` (padrão 100 por 60s), por usuário autenticado ou, sem token, por IP. Requisições com 401 também contam para o IP.

## `GET /health`

Consulta o `/health` de cada serviço e devolve `status` `ok` (todos no ar) ou `degraded`, com `dependencies.<servico>.status` `up`/`down`. Sempre 200 enquanto o gateway estiver de pé.

## Interface Web (Frontend)

O gateway serve uma interface mínima SPA cobrindo os casos de uso de investidor:
- `GET /`: página principal da aplicação web (`static/index.html`)
- `GET /static/{arquivo}`: recursos estáticos (`styles.css`, `app.js`) com proteção contra path traversal.

### Fluxos suportados:
1. **Cadastro e Login**: registro de novos usuários e obtenção de token JWT.
2. **KYC**: envio de documento e acompanhamento do status cadastral.
3. **Campanhas**: visualização de campanhas ativas com indicador de progresso da meta e prazo.
4. **Aportes**: submissão de aporte gerando cabeçalho `Idempotency-Key` (UUIDv4), com feedback de erros (ex.: KYC pendente ou campanha encerrada).
5. **Histórico e Notificações**: listagem dos aportes realizados pelo investidor, retornos e notificações em tempo real com opção de marcar como lida.

## Rodando

`make dev` sobe o gateway por último. Sozinho: `uv run python -m gateway.main`.
