CREATE TABLE IF NOT EXISTS aporte (
    id TEXT PRIMARY KEY,
    campanha_id TEXT NOT NULL,
    investidor_id TEXT NOT NULL,
    valor INTEGER NOT NULL CHECK (valor > 0),
    status TEXT NOT NULL DEFAULT 'PENDENTE'
        CHECK (status IN ('PENDENTE', 'CONFIRMADO', 'REJEITADO')),
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_aporte_campanha
ON aporte (campanha_id);

CREATE INDEX IF NOT EXISTS idx_aporte_investidor
ON aporte (investidor_id);