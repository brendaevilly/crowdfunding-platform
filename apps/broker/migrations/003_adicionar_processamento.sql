
-- Adiciona suporte ao estado de processamento das entregas.
-- Reconstrói a tabela para atualizar a restrição CHECK.

CREATE TABLE broker_deliveries_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    subscription_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            status IN (
                'pending',
                'processing',
                'delivered',
                'dlq'
            )
        ),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    delivered_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (event_id)
        REFERENCES broker_events(id),

    FOREIGN KEY (subscription_id)
        REFERENCES broker_subscriptions(id),

    UNIQUE(event_id, subscription_id)
);

INSERT INTO broker_deliveries_new (
    id,
    event_id,
    subscription_id,
    status,
    attempts,
    next_attempt_at,
    last_error,
    delivered_at,
    created_at
)
SELECT
    id,
    event_id,
    subscription_id,
    status,
    attempts,
    next_attempt_at,
    last_error,
    delivered_at,
    created_at
FROM broker_deliveries;

DROP TABLE broker_deliveries;

ALTER TABLE broker_deliveries_new
RENAME TO broker_deliveries;

CREATE INDEX idx_broker_deliveries_pending
ON broker_deliveries(status, next_attempt_at);
