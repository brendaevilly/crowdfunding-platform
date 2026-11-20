# campanhas

Microsserviço de **Gestão de Campanhas** (Core Domain).

- **Porta padrão:** `3002` (definida em `services.json`).
- **Banco de dados:** SQLite exclusivo em `data/campanhas.db`.
- **Regras arquiteturais:** depende unicamente de `packages/*` (`contracts` e `shared`) e nunca importa código de outros microsserviços (ADR-001).

---

## 1. Modelo de Domínio e Agregado Campanha

O agregado raiz `Campanha` encapsula as regras centrais de captação de recursos:

- **Value Objects:**
  - `Meta`: valor monetário estritamente positivo em centavos inteiros (`meta > 0`).
  - `Prazo`: período de vigência temporal onde a data final é estritamente posterior à data inicial (`fim > inicio`).
- **Concorrência Otimista:**
  - Campo `versao` inteiro (inicia em `1` e incrementa a cada mutação). Atualizações validam `WHERE id = ? AND versao = ?`. Caso haja incompatibilidade, retorna `409 Conflict`.
- **Regra de Edição:**
  - Apenas campanhas no status `RASCUNHO` podem ser editadas (`PUT /campanhas/:id`). Tentativas de edição em outros estados são rejeitadas com `409 Conflict`.
  - Apenas o empreendedor dono da campanha (`empreendedorId` coincidente com `X-User-ID`) tem autorização para edição (rejeição com `403 Forbidden`).

---

## 2. Projeção Local de Usuários (`usuarios_cache`)

Para preservar a autonomia do microsserviço e evitar acoplamento síncrono em runtime com a Identidade:

- **Eventos Consumidos:**
  - `usuario.cadastrado` (`UsuarioCadastrado`): projeta o cadastro do usuário com seu perfil (`EMPREENDEDOR`, `INVESTIDOR`, `ADMIN`).
  - `usuario.status-alterado` (`UsuarioStatusAlterado`): atualiza o status de bloqueio/desbloqueio (`ATIVO`, `BLOQUEADO`), respeitando monotonicidade temporal (`alteradoEm`).
- **Regra de Criação de Campanhas:**
  - Apenas usuários com `perfil == "EMPREENDEDOR"` e status `"ATIVO"` podem criar campanhas.
  - Tentativas por usuários com perfil `INVESTIDOR` ou status `BLOQUEADO` são bloqueadas com código HTTP `403 Forbidden`.

---

## 3. Endpoints HTTP da API

Prefixos suportados diretamente no serviço ou roteados pelo Gateway (`/api/campanhas/*` encaminhado para `/campanhas/*`):

| Método | Caminho | Descrição | Permissão | Status Sucesso |
|---|---|---|---|---|
| `POST` | `/campanhas` | Cria uma nova campanha no status `RASCUNHO` | `EMPREENDEDOR` ativo | `201 Created` |
| `GET` | `/campanhas/{id}` | Consulta detalhes e dados completos da campanha | Público / Autenticado | `200 OK` |
| `PUT` | `/campanhas/{id}` | Atualiza dados (meta, prazo, título, descrição) de um rascunho | Empreendedor dono | `200 OK` |
| `GET` | `/campanhas/{id}/status` | Endpoint síncrono de status consumido por Aportes | Serviços da plataforma | `200 OK` |

### Tratamento de Erros

Os erros seguem o padrão da plataforma: `{"error": {"code", "message", "details", "correlationId"}}`:
- `400 Bad Request`: identificação do empreendedor ausente.
- `403 Forbidden`: usuário sem permissão (não é empreendedor ativo ou não é dono da campanha).
- `404 Not Found`: campanha não encontrada.
- `409 Conflict`: edição fora de `RASCUNHO` ou conflito de concorrência de versão.
- `422 Unprocessable Entity`: meta inválida (<= 0) ou prazo final anterior/igual ao inicial.

---

## 4. Testes

```bash
# Executar todos os testes de campanhas:
uv run python -m pytest apps/campanhas/tests -v

# Validações de código e tipagem:
uv run python -m ruff check apps/campanhas
uv run python -m mypy apps/campanhas
```
