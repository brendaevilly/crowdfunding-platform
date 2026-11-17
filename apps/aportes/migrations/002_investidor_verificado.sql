CREATE TABLE IF NOT EXISTS investidor_verificado (
    investidor_id TEXT PRIMARY KEY,
    verificado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);