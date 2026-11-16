# contracts

Contratos versionados: eventos e endpoints síncronos tipados (pydantic v2). Todo serviço importa os schemas daqui; nenhum app define payload por conta própria.

Catálogo completo (gerado do código): [`docs/contratos/CATALOGO.md`](../../docs/contratos/CATALOGO.md).

## Publicar um evento

```python
from contracts import AporteConfirmado, criar_envelope, topicos

evento = AporteConfirmado(
    aporte_id="a1", campanha_id="c1", investidor_id="u1", valor=500, confirmado_em=agora_utc
)
envelope = criar_envelope(evento, correlation_id=correlation_id)  # tópico e versão vêm do catálogo
corpo = envelope.para_json()  # POST /publish no broker; campos em camelCase
```

## Consumir um evento

```python
from contracts import chave_idempotencia, ler_envelope

envelope = ler_envelope(corpo_recebido)  # valida tópico, schemaVersion e payload
chave = chave_idempotencia(envelope)  # valor a gravar em evento_processado(chave UNIQUE)
```

`ler_envelope` levanta `ContratoInvalido` para tópico desconhecido, versão não suportada ou payload fora do schema.

## Regras

- Campos em snake_case no Python e **camelCase** no JSON; modelos imutáveis e sem campos extras.
- Valores monetários em **centavos** (inteiros); datas com fuso (UTC).
- Nomes de tópico só em `contracts.topicos`. Mudança incompatível de payload = novo `schemaVersion`.
- Alterou um contrato? Atualize o catálogo e rode `make contratos`; o `make check` falha se `docs/contratos/` estiver desatualizado.
- `contracts.exemplos` traz uma instância válida de cada evento para testes de contrato dos serviços.
