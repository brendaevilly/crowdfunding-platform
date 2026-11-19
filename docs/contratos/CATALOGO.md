# Catálogo de contratos

> Gerado por `scripts/gen_contratos_doc.py` a partir de `packages/contracts`. **Não edite à mão**: altere o código e rode o script.

Envelope de todo evento (schemaVersion atual: **1**): `eventId`, `topic`, `schemaVersion`, `occurredAt`, `correlationId`, `payload`. Valores monetários em centavos (inteiros). JSON em camelCase.

## Eventos

### UsuarioCadastrado (`usuario.cadastrado`)

- **Produtor:** identidade (contas)
- **Chave de idempotência:** `usuarioId`
- **Consumidores:**
  - `campanhas`: cria a projeção local do usuário
  - `identidade (kyc)`: abre a verificação de identidade

| Campo | Tipo | Obrigatório |
|---|---|---|
| `usuarioId` | string | sim |
| `perfil` | EMPREENDEDOR \| INVESTIDOR \| ADMIN | sim |
| `cadastradoEm` | data/hora UTC (ISO 8601) | sim |

### UsuarioStatusAlterado (`usuario.status-alterado`)

- **Produtor:** identidade (contas)
- **Chave de idempotência:** `eventId`
- **Consumidores:**
  - `campanhas`: bloqueia/libera a publicação de campanhas (cada evento é uma transição)
  - `aportes`: bloqueia/libera novos aportes

| Campo | Tipo | Obrigatório |
|---|---|---|
| `usuarioId` | string | sim |
| `statusAnterior` | ATIVO \| BLOQUEADO | sim |
| `statusNovo` | ATIVO \| BLOQUEADO | sim |
| `motivo` | string (opcional) | não |
| `alteradoEm` | data/hora UTC (ISO 8601) | sim |

### IdentidadeVerificada (`identidade.verificada`)

- **Produtor:** identidade (kyc)
- **Chave de idempotência:** `usuarioId`
- **Consumidores:**
  - `aportes`: marca o investidor como verificado (via camada anticorrupção)

| Campo | Tipo | Obrigatório |
|---|---|---|
| `usuarioId` | string | sim |
| `verificadaEm` | data/hora UTC (ISO 8601) | sim |

### CampanhaPublicada (`campanha.publicada`)

- **Produtor:** campanhas
- **Chave de idempotência:** `campanhaId`
- **Consumidores:**
  - `custodia_retornos (custódia)`: abre a ContaCustodia e agenda a apuração em prazoFim

| Campo | Tipo | Obrigatório |
|---|---|---|
| `campanhaId` | string | sim |
| `empreendedorId` | string | sim |
| `meta` | inteiro (centavos) | sim |
| `prazoFim` | data/hora UTC (ISO 8601) | sim |

### TotalArrecadadoAtualizado (`campanha.total-arrecadado-atualizado`)

- **Produtor:** custodia_retornos (custódia)
- **Chave de idempotência:** `eventId`
- **Consumidores:**
  - `campanhas`: atualiza valorAcumulado (monotônico: ignora valor menor que o atual)

| Campo | Tipo | Obrigatório |
|---|---|---|
| `campanhaId` | string | sim |
| `valorAcumulado` | inteiro (centavos) | sim |

### AporteConfirmado (`aporte.confirmado`)

- **Produtor:** aportes
- **Chave de idempotência:** `aporteId`
- **Consumidores:**
  - `custodia_retornos (custódia)`: registra a RETENCAO do valor na ContaCustodia

| Campo | Tipo | Obrigatório |
|---|---|---|
| `aporteId` | string | sim |
| `campanhaId` | string | sim |
| `investidorId` | string | sim |
| `valor` | inteiro (centavos) | sim |
| `confirmadoEm` | data/hora UTC (ISO 8601) | sim |

### CampanhaLiquidada (`campanha.liquidada`)

- **Produtor:** custodia_retornos (custódia)
- **Chave de idempotência:** `campanhaId`
- **Consumidores:**
  - `custodia_retornos (retornos)`: calcula e distribui os retornos aos investidores

| Campo | Tipo | Obrigatório |
|---|---|---|
| `campanhaId` | string | sim |
| `valorBruto` | inteiro (centavos) | sim |
| `taxaPlataforma` | inteiro (centavos) | sim |
| `valorLiquido` | inteiro (centavos) | sim |
| `liquidadaEm` | data/hora UTC (ISO 8601) | sim |

### ResultadoCampanha (`campanha.resultado`)

- **Produtor:** custodia_retornos (custódia)
- **Chave de idempotência:** `campanhaId`
- **Consumidores:**
  - `campanhas`: encerra a campanha com o resultado
  - `notificacao`: avisa o empreendedor e os investidores

| Campo | Tipo | Obrigatório |
|---|---|---|
| `campanhaId` | string | sim |
| `empreendedorId` | string | sim |
| `resultado` | SUCESSO \| FALHA | sim |
| `valorArrecadado` | inteiro (centavos) | sim |
| `investidorIds` | lista de typing.Annotated[str, StringConstraints(strip_whitespace=True, to_upper=None, to_lower=None, strict=None, min_length=1, max_length=64, pattern=None, ascii_only=None)] | sim |
| `encerradaEm` | data/hora UTC (ISO 8601) | sim |

### RetornoDistribuido (`retorno.distribuido`)

- **Produtor:** custodia_retornos (retornos)
- **Chave de idempotência:** `(investidorId, eventoOrigemId)`
- **Consumidores:**
  - `notificacao`: avisa o investidor do retorno recebido

| Campo | Tipo | Obrigatório |
|---|---|---|
| `retornoId` | string | sim |
| `campanhaId` | string | sim |
| `investidorId` | string | sim |
| `valor` | inteiro (centavos) | sim |
| `eventoOrigemId` | string | sim |
| `distribuidoEm` | data/hora UTC (ISO 8601) | sim |

## Endpoint síncrono (Aportes → Campanhas)

`GET /campanhas/:id/status`

| Campo | Tipo | Obrigatório |
|---|---|---|
| `campanhaId` | string | sim |
| `status` | RASCUNHO \| PUBLICADA \| ENCERRADA \| CANCELADA | sim |

Somente `PUBLICADA` aceita aportes. Sem resposta ou erro: o aporte é rejeitado (fail-safe).

## Correções aplicadas (seção 8 de ARQUITETURA_LOCAL.md)

- **LC-01** CampanhaPublicada vira contrato entre Campanhas e Custódia. Custódia precisa de campanhaId, meta, prazoFim e empreendedorId para abrir a ContaCustodia e agendar a apuração.
- **LC-02** Notificação recebe os destinatários. ResultadoCampanha traz empreendedorId e investidorIds; RetornoDistribuido traz investidorId.
- **LC-03** Contrato de Notificação lista RetornoDistribuido. RetornoDistribuido substitui CampanhaLiquidada no contrato de Notificação.
- **LC-04** Novo evento UsuarioStatusAlterado. Campanhas e Aportes passam a saber do bloqueio/desbloqueio de usuário por evento.
- **LC-05** Taxa da plataforma calculada na LIBERACAO da Custódia. CampanhaLiquidada informa valorBruto, taxaPlataforma e valorLiquido (valorBruto = taxaPlataforma + valorLiquido).
- **LC-06** CampanhaLiquidada só em sucesso. Na falha ocorrem as DEVOLUCOES e apenas ResultadoCampanha é emitido.
