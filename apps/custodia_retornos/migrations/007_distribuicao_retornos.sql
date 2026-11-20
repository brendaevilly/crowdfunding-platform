-- Lotes financeiros de distribuição de retornos.
-- Diferente de retornos_distribuicoes, permite vários lotes por campanha.

CREATE TABLE IF NOT EXISTS retornos_lotes_distribuicao (
    lote_id TEXT PRIMARY KEY,
    campanha_id TEXT NOT NULL,
    empreendedor_id TEXT NOT NULL,
    valor_total INTEGER NOT NULL CHECK (valor_total > 0),
    distribuido_em TEXT NOT NULL,

    FOREIGN KEY (campanha_id)
        REFERENCES custodia_contas(campanha_id)
);

CREATE INDEX IF NOT EXISTS idx_retornos_lotes_campanha
ON retornos_lotes_distribuicao(campanha_id);

-- Valores efetivamente recebidos por cada investidor.
CREATE TABLE IF NOT EXISTS retornos_distribuicao_itens (
    retorno_id TEXT PRIMARY KEY,
    lote_id TEXT NOT NULL,
    campanha_id TEXT NOT NULL,
    investidor_id TEXT NOT NULL,
    valor INTEGER NOT NULL CHECK (valor > 0),
    distribuido_em TEXT NOT NULL,

    UNIQUE (lote_id, investidor_id),

    FOREIGN KEY (lote_id)
        REFERENCES retornos_lotes_distribuicao(lote_id),

    FOREIGN KEY (campanha_id)
        REFERENCES custodia_contas(campanha_id)
);

CREATE INDEX IF NOT EXISTS idx_distribuicao_itens_investidor
ON retornos_distribuicao_itens(investidor_id);

CREATE INDEX IF NOT EXISTS idx_distribuicao_itens_campanha
ON retornos_distribuicao_itens(campanha_id);

-- Histórico financeiro append-only.
CREATE TRIGGER IF NOT EXISTS
    trg_lotes_distribuicao_nao_atualizar
BEFORE UPDATE ON retornos_lotes_distribuicao
BEGIN
    SELECT RAISE(ABORT, 'Lotes de distribuicao sao imutaveis');
END;

CREATE TRIGGER IF NOT EXISTS
    trg_lotes_distribuicao_nao_excluir
BEFORE DELETE ON retornos_lotes_distribuicao
BEGIN
    SELECT RAISE(ABORT, 'Lotes de distribuicao nao podem ser excluidos');
END;

CREATE TRIGGER IF NOT EXISTS
    trg_distribuicao_itens_nao_atualizar
BEFORE UPDATE ON retornos_distribuicao_itens
BEGIN
    SELECT RAISE(ABORT, 'Distribuicoes sao imutaveis');
END;

CREATE TRIGGER IF NOT EXISTS
    trg_distribuicao_itens_nao_excluir
BEFORE DELETE ON retornos_distribuicao_itens
BEGIN
    SELECT RAISE(ABORT, 'Distribuicoes nao podem ser excluidas');
END;
