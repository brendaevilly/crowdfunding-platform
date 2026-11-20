ALTER TABLE campanhas ADD COLUMN meta_atingida INTEGER GENERATED ALWAYS AS (valor_arrecadado >= meta) VIRTUAL;

CREATE INDEX IF NOT EXISTS idx_campanhas_status ON campanhas(status);
