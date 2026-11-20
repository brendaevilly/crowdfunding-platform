# Microsserviço de Custódia e Retornos

Responsável pelas contas de custódia e pela retenção dos aportes confirmados. A liquidação e a distribuição de retornos serão implementadas em etapas posteriores.

## Arquitetura

- Serviço: `custodia_retornos`
- Porta padrão: `3004` (`services.json`)
- Framework: FastAPI
- Banco de dados: SQLite exclusivo do serviço
- Comunicação: broker local de eventos
- Módulos: `custodia` e `retornos`

O serviço segue `docs/adr/ADR-001-arquitetura-microsservicos-local.md` e não importa código de outros microsserviços.

## Executar

Na raiz do monorepo:

```bash
uv run python -m custodia_retornos.main
```

O broker local também deve estar em execução para entregar eventos.

## Eventos consumidos

### CampanhaPublicada

- Valida os dados da campanha.
- Abre uma conta de custódia com `campanha_id`, `meta` e `prazo_fim`.
- Inicializa `saldo_retido` em zero.
- Garante uma única conta por campanha, mesmo com entregas repetidas.

### AporteConfirmado

- Verifica se a conta da campanha existe.
- Registra uma movimentação `RETENCAO`.
- Atualiza o saldo retido na mesma transação.
- Impede retenções duplicadas para o mesmo aporte.

Se o aporte chegar antes da publicação da campanha, o processamento falha sem registrar a retenção, permitindo nova tentativa pelo broker.

As tentativas são limitadas pela configuração do broker. Eventos enviados à DLQ podem exigir reprocessamento.

## Persistência

### custodia_contas

Campos: `campanha_id`, `meta`, `prazo_fim`, `saldo_retido`, `criada_em`.

### custodia_movimentacoes

Campos: `movimentacao_id`, `campanha_id`, `aporte_id`, `tipo`, `valor`, `criada_em`.

## Garantias de integridade

- Uma conta por campanha.
- Uma retenção por aporte, protegida por índice UNIQUE parcial.
- Movimentações append-only, protegidas por triggers SQLite.
- Valores monetários representados por inteiros em centavos.
- Retenção e atualização do saldo na mesma transação.
- Saldo retido igual à soma das retenções registradas nesta etapa.

Os tipos `LIBERACAO` e `DEVOLUCAO` estão previstos para etapas futuras.

## Testes

Testes da Custódia:

```bash
PYTHONPATH=scripts uv run pytest apps/custodia_retornos/tests/custodia/ -v
```

Suíte completa:

```bash
uv run pytest
```

Qualidade e tipagem:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Os testes verificam idempotência, retenção, imutabilidade, reprocessamento de eventos e a propriedade de igualdade entre saldo e soma das retenções.
