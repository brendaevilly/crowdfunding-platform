
-- Registra a sinalização de pendências de retenção atrasadas.
-- Não altera o status financeiro do aporte.

ALTER TABLE aporte_custodia
ADD COLUMN sinalizado_em TEXT;

CREATE INDEX IF NOT EXISTS idx_aporte_custodia_pendentes
ON aporte_custodia (status, criado_em);
