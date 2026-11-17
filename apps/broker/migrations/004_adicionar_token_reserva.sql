
-- Adiciona um identificador exclusivo para cada reserva.

ALTER TABLE broker_deliveries
ADD COLUMN lease_token TEXT;

-- Identifica reservas em processamento.
CREATE INDEX IF NOT EXISTS idx_broker_deliveries_lease
ON broker_deliveries(status, lease_token);

-- Limpa possíveis tokens antigos guardados em last_error.
-- Preserva last_error das entregas pendentes e da DLQ.
UPDATE broker_deliveries
SET status = 'pending',
    next_attempt_at = NULL,
    last_error = NULL,
    lease_token = NULL
WHERE status = 'processing';
