
CREATE TABLE IF NOT EXISTS broker_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    payload TEXT NOT NULL,
    correlation_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS broker_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    subscription_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'delivered', 'dlq')),
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

CREATE INDEX IF NOT EXISTS idx_broker_deliveries_pending
ON broker_deliveries(status, next_attempt_at);
