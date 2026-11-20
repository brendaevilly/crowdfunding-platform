CREATE TABLE IF NOT EXISTS custodia_contas (
    campanha_id TEXT PRIMARY KEY,
    meta INTEGER NOT NULL CHECK (meta > 0),
    prazo_fim TEXT NOT NULL,
    saldo_retido INTEGER NOT NULL DEFAULT 0
        CHECK (saldo_retido >= 0),
    criada_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS custodia_movimentacoes (
    movimentacao_id TEXT PRIMARY KEY,
    campanha_id TEXT NOT NULL,
    aporte_id TEXT,
    tipo TEXT NOT NULL CHECK (
        tipo IN ('RETENCAO', 'LIBERACAO', 'DEVOLUCAO')
    ),
    valor INTEGER NOT NULL CHECK (valor > 0),
    criada_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (campanha_id)
        REFERENCES custodia_contas(campanha_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_custodia_retencao_aporte
ON custodia_movimentacoes(aporte_id)
WHERE tipo = 'RETENCAO';


-- Movimentações financeiras são append-only.
CREATE TRIGGER IF NOT EXISTS trg_custodia_movimentacao_nao_atualizar
BEFORE UPDATE ON custodia_movimentacoes
BEGIN
    SELECT RAISE(ABORT, 'Movimentacoes de custodia sao imutaveis');
END;

CREATE TRIGGER IF NOT EXISTS trg_custodia_movimentacao_nao_excluir
BEFORE DELETE ON custodia_movimentacoes
BEGIN
    SELECT RAISE(ABORT, 'Movimentacoes de custodia nao podem ser excluidas');
END;
