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

## 2. Ciclo de Vida e Máquina de Estados

```text
[RASCUNHO]
    │
    │  POST /campanhas/:id/submeter (empreendedor dono)
    ▼
[EM_MODERACAO]
    ├── POST /campanhas/:id/aprovar (ADMIN)  ──>  [PUBLICADA] (ativa, emite evento)
    │
    └── POST /campanhas/:id/reprovar (ADMIN) ──>  [REPROVADA] (terminal)
```

- **Transições Permitidas:**
  - `RASCUNHO` -> `EM_MODERACAO`: submissão realizada pelo empreendedor dono.
  - `EM_MODERACAO` -> `PUBLICADA`: aprovação exclusiva de administradores (`X-User-Perfil: ADMIN`).
  - `EM_MODERACAO` -> `REPROVADA`: reprovação exclusiva de administradores com preenchimento obrigatório de justificativa (`motivo`).
- **Regra 9 (REPROVADA nunca vira ATIVA):**
  - O estado `REPROVADA` é terminal e irreversível.
  - Tentativas de submissão, aprovação ou edição de uma campanha reprovada são rejeitadas com `409 Conflict`.

---

## 3. Mensageria e Consumo de Eventos

- **Eventos de Identidade Consumidos:**
  - `usuario.cadastrado` (`UsuarioCadastrado`): projeta o cadastro do usuário na tabela `usuarios_cache` com seu perfil (`EMPREENDEDOR`, `INVESTIDOR`, `ADMIN`).
  - `usuario.status-alterado` (`UsuarioStatusAlterado`): atualiza o status de bloqueio/desbloqueio (`ATIVO`, `BLOQUEADO`), respeitando monotonicidade temporal (`alteradoEm`).
- **Eventos de Custódia/Pagamentos Consumidos (#20):**
  - `campanha.total-arrecadado-atualizado` (`TotalArrecadadoAtualizado`): atualização estritamente crescente e monotônica de `valor_arrecadado` (`WHERE id = ? AND ? > valor_arrecadado`). Eventos fora de ordem ou com valores menores/iguais são ignorados sem disparar erro ou rollback.
  - `campanha.resultado` (`ResultadoCampanha`): transiciona a campanha de `PUBLICADA` para `ENCERRADA`. É idempotente por agregado (`campanhaId`): se a campanha já se encontrar `ENCERRADA`, execuções subsequentes atuam como no-op seguro.
- **Evento Publicado na Aprovação (`CampanhaPublicada`):**
  - Ao aprovar uma campanha (`POST /campanhas/:id/aprovar`), o microsserviço insere o evento no tópico `campanha.publicada` na tabela `outbox_evento` **dentro da mesma transação atômica** em que o status é atualizado para `PUBLICADA`.
  - O payload segue o contrato `contracts.eventos.CampanhaPublicada`:
    ```json
    {
      "campanhaId": "uuid",
      "empreendedorId": "uuid",
      "meta": 1000000,
      "prazoFim": "2026-12-20T12:00:00+00:00"
    }
    ```
  - Nem a submissão nem a reprovação publicam esse evento.

---

## 4. Endpoints HTTP da API

Prefixos suportados diretamente no serviço ou roteados pelo Gateway (`/api/campanhas/*` encaminhado para `/campanhas/*`):

| Método | Caminho | Descrição | Permissão | Status Sucesso |
|---|---|---|---|---|
| `POST` | `/campanhas` | Cria uma nova campanha no status `RASCUNHO` | `EMPREENDEDOR` ativo | `201 Created` |
| `GET` | `/campanhas` | Listagem pública/ativas com paginação (`limite`, `offset`) via réplica de leitura | Autenticado | `200 OK` |
| `GET` | `/campanhas/{id}` | Consulta detalhes completos da campanha | Autenticado | `200 OK` |
| `PUT` | `/campanhas/{id}` | Atualiza dados (meta, prazo, título, descrição) de um rascunho | Empreendedor dono | `200 OK` |
| `POST` | `/campanhas/{id}/submeter` | Envia a campanha para a fila de moderação | Empreendedor dono | `200 OK` |
| `POST` | `/campanhas/{id}/aprovar` | Aprova campanha e publica `CampanhaPublicada` | `ADMIN` | `200 OK` |
| `POST` | `/campanhas/{id}/reprovar` | Reprova campanha registrando motivo (Regra 9) | `ADMIN` | `200 OK` |
| `GET` | `/campanhas/{id}/status` | Consulta síncrona de status (conexão primária/escrita, Regra 2) | Serviços internos | `200 OK` |

### Consulta Síncrona de Status (Regra 2) e CQRS Leve

- **Decisão de Aportes na Conexão Primária:**
  - O endpoint `GET /campanhas/{id}/status` consulta sempre a conexão de escrita primária, eliminando risco de leitura defasada por replicação.
  - **Regra 2:** responde `PUBLICADA` apenas se o status for `PUBLICADA` e a data/hora atual estiver estritamente dentro do prazo (`agora <= prazoFim`). Se o prazo tiver expirado, responde `ENCERRADA` mesmo que o status no banco ainda não tenha sido alterado.
- **Listagem Pública com Paginação e Simulação de Réplica:**
  - `GET /campanhas` utiliza conexão de leitura dedicada (`executar_leitura`), simulando a réplica de leitura para suportar alto volume.
  - Suporta paginação via query parameters `limite` (padrão 20, máx 100) e `offset` (padrão 0), além de filtros por `status` (ex.: `status=ATIVA` ou `status=EM_MODERACAO`).
- **Coluna Gerada `meta_atingida`:**
  - Adicionada via migration `002_adicionar_meta_atingida.sql`: `INTEGER GENERATED ALWAYS AS (valor_arrecadado >= meta) VIRTUAL`.
  - É calculada nativamente pelo SQLite e **não é gravável** (tentativas de inserção explícita disparam erro no SQLite).
  - Incluída em todas as respostas de campanha (`metaAtingida` / `meta_atingida`).

### Tratamento de Erros

Os erros seguem o padrão da plataforma: `{"error": {"code", "message", "details", "correlationId"}}`:
- `400 Bad Request`: identificação do empreendedor ausente.
- `403 Forbidden`: permissão negada (não é empreendedor ativo, não é dono da campanha ou não é administrador).
- `404 Not Found`: campanha não encontrada.
- `409 Conflict`: transição inválida de estado (ex.: edição fora de rascunho, violação da Regra 9) ou concorrência otimista.
- `422 Unprocessable Entity`: meta <= 0, prazo final anterior/igual ao inicial ou motivo de reprovação vazio.

---

## 5. Testes

```bash
# Executar todos os testes de campanhas:
uv run python -m pytest apps/campanhas/tests -v

# Validações de código e tipagem:
uv run python -m ruff check apps/campanhas
uv run python -m mypy apps/campanhas
```
