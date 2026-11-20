-- Histórico de verificações de identidade.
CREATE TABLE IF NOT EXISTS kyc_verificacoes (
    id TEXT PRIMARY KEY,
    usuario_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDENTE'
        CHECK (status IN ('PENDENTE', 'APROVADA', 'REPROVADA', 'EXPIRADA')),
    documento_tipo TEXT,
    documento_hash TEXT,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES contas_usuarios(id)
);

-- Garante no máximo uma verificação pendente por usuário.
CREATE UNIQUE INDEX IF NOT EXISTS idx_kyc_pendente_usuario
ON kyc_verificacoes(usuario_id)
WHERE status = 'PENDENTE';

-- Facilita a consulta do histórico.
CREATE INDEX IF NOT EXISTS idx_kyc_usuario
ON kyc_verificacoes(usuario_id);

-- Impede alterações em verificações aprovadas.
CREATE TRIGGER IF NOT EXISTS trg_kyc_aprovada_imutavel
BEFORE UPDATE ON kyc_verificacoes
WHEN OLD.status = 'APROVADA'
BEGIN
    SELECT RAISE(ABORT, 'Verificacao APROVADA e imutavel');
END;

-- Impede exclusão de verificações aprovadas.
CREATE TRIGGER IF NOT EXISTS trg_kyc_aprovada_nao_excluir
BEFORE DELETE ON kyc_verificacoes
WHEN OLD.status = 'APROVADA'
BEGIN
    SELECT RAISE(ABORT, 'Verificacao APROVADA nao pode ser excluida');
END;

-- Registra o processamento inicial por usuarioId, independentemente do eventId.
CREATE TABLE IF NOT EXISTS kyc_usuarios_inicializados (
    usuario_id TEXT PRIMARY KEY,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES contas_usuarios(id)
);
