CREATE TABLE IF NOT EXISTS investidor_status (
    investidor_id TEXT PRIMARY KEY,
    status TEXT NOT NULL
        CHECK (status IN ('ATIVO', 'BLOQUEADO')),
    alterado_em TEXT NOT NULL
);
