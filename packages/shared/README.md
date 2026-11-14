# shared

Utilitários compartilhados: HTTP, banco, outbox, correlation-id.



## Convenção de nomes de tabelas

Cada serviço utiliza seu próprio banco SQLite.

Quando um serviço agrupa mais de um bounded context,
as tabelas devem começar com o prefixo do contexto.

Exemplo para o serviço custodia_retornos:

- Custódia: prefixo `custodia_`
- Retornos: prefixo `retornos_`

Exemplos de tabelas:

- `custodia_saldos`
- `custodia_movimentacoes`
- `retornos_distribuicoes`
- `retornos_participacoes`

Os nomes devem utilizar letras minúsculas e snake_case.

Serviços não devem acessar diretamente tabelas
ou bancos de outros serviços.
