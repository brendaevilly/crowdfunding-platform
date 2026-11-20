CREATE TABLE IF NOT EXISTS notificacao (
    id TEXT PRIMARY KEY,
    usuario_id TEXT NOT NULL,
    evento_origem_id TEXT NOT NULL,
    tipo_evento TEXT NOT NULL,
    titulo TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    status_envio TEXT NOT NULL CHECK(status_envio IN ('ENVIADA', 'FALHA')),
    lida INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    enviado_em TEXT,
    UNIQUE(usuario_id, evento_origem_id)
);

CREATE INDEX IF NOT EXISTS idx_notificacao_usuario ON notificacao(usuario_id);
CREATE INDEX IF NOT EXISTS idx_notificacao_criado_em ON notificacao(criado_em);
