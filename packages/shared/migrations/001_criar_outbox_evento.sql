CREATE TABLE IF NOT EXISTS outbox_evento (
    outbox_id TEXT PRIMARY KEY,
    agregado_id TEXT NOT NULL,
    tipo_evento TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDENTE',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TEXT
);
