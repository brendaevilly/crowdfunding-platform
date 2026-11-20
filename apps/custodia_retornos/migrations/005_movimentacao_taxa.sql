-- Permite registrar a taxa da plataforma no próprio extrato.
-- Preserva todas as movimentações anteriores.

DROP INDEX IF EXISTS ux_custodia_retencao_aporte;
DROP INDEX IF EXISTS ux_custodia_devolucao_aporte;
DROP INDEX IF EXISTS ux_custodia_liberacao_campanha;

CREATE TABLE custodia_movimentacoes_nova (
    movimentacao_id TEXT PRIMARY KEY,
    campanha_id TEXT NOT NULL,
    aporte_id TEXT,
    tipo TEXT NOT NULL CHECK (
        tipo IN ('RETENCAO', 'LIBERACAO', 'DEVOLUCAO', 'TAXA')
    ),
    valor INTEGER NOT NULL CHECK (valor > 0),
    criada_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (campanha_id)
        REFERENCES custodia_contas(campanha_id)
);

INSERT INTO custodia_movimentacoes_nova (
    movimentacao_id, campanha_id, aporte_id, tipo, valor, criada_em
)
SELECT
    movimentacao_id, campanha_id, aporte_id, tipo, valor, criada_em
FROM custodia_movimentacoes;

DROP TABLE custodia_movimentacoes;

ALTER TABLE custodia_movimentacoes_nova
RENAME TO custodia_movimentacoes;

CREATE UNIQUE INDEX ux_custodia_retencao_aporte
ON custodia_movimentacoes(aporte_id)
WHERE tipo = 'RETENCAO';

CREATE UNIQUE INDEX ux_custodia_devolucao_aporte
ON custodia_movimentacoes(aporte_id)
WHERE tipo = 'DEVOLUCAO';

CREATE UNIQUE INDEX ux_custodia_liberacao_campanha
ON custodia_movimentacoes(campanha_id)
WHERE tipo = 'LIBERACAO';

CREATE UNIQUE INDEX ux_custodia_taxa_campanha
ON custodia_movimentacoes(campanha_id)
WHERE tipo = 'TAXA';

CREATE TRIGGER trg_custodia_movimentacao_nao_atualizar
BEFORE UPDATE ON custodia_movimentacoes
BEGIN
    SELECT RAISE(ABORT, 'Movimentacoes de custodia sao imutaveis');
END;

CREATE TRIGGER trg_custodia_movimentacao_nao_excluir
BEFORE DELETE ON custodia_movimentacoes
BEGIN
    SELECT RAISE(ABORT, 'Movimentacoes de custodia nao podem ser excluidas');
END;
