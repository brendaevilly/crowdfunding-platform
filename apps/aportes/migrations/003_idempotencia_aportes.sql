-- Armazena o resultado de cada requisição POST /aportes.
-- A chave é única para impedir o processamento duplicado.

CREATE TABLE IF NOT EXISTS aporte_requisicao (
    idempotency_key TEXT PRIMARY KEY,
    aporte_id TEXT,
    campanha_id TEXT NOT NULL,
    investidor_id TEXT NOT NULL,
    valor INTEGER NOT NULL CHECK (valor > 0),
    status_http INTEGER NOT NULL,
    resposta_json TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (aporte_id) REFERENCES aporte(id)
);

CREATE INDEX IF NOT EXISTS idx_aporte_requisicao_aporte
ON aporte_requisicao (aporte_id);
