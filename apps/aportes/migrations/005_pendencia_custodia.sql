
-- Controla a reconciliação de aportes confirmados com Custódia.
-- O status do aporte permanece CONFIRMADO no domínio de Aportes.
-- A pendência representa apenas o processamento ainda não conciliado.

CREATE TABLE IF NOT EXISTS aporte_custodia (
    aporte_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'PENDENTE'
        CHECK (status IN ('PENDENTE', 'CONCILIADO')),
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    conciliado_em TEXT,
    FOREIGN KEY (aporte_id) REFERENCES aporte(id)
);

CREATE INDEX IF NOT EXISTS idx_aporte_custodia_status
ON aporte_custodia (status);
