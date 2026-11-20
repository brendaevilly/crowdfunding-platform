CREATE TABLE IF NOT EXISTS campanhas (
    id TEXT PRIMARY KEY,
    empreendedor_id TEXT NOT NULL,
    titulo TEXT NOT NULL,
    descricao TEXT NOT NULL,
    meta INTEGER NOT NULL,
    prazo_inicio TEXT NOT NULL,
    prazo_fim TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'RASCUNHO',
    valor_arrecadado INTEGER NOT NULL DEFAULT 0,
    motivo_reprovacao TEXT,
    versao INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_campanhas_empreendedor ON campanhas(empreendedor_id);
CREATE INDEX IF NOT EXISTS idx_campanhas_status ON campanhas(status);

CREATE TABLE IF NOT EXISTS usuarios_cache (
    usuario_id TEXT PRIMARY KEY,
    perfil TEXT NOT NULL,
    status TEXT NOT NULL,
    alterado_em TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_usuarios_cache_status ON usuarios_cache(usuario_id, status);
