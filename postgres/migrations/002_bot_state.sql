-- Key/value storage for bot state that needs to survive a restart.

CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO bot_state (key, value) VALUES ('staff_ping_index', '0')
ON CONFLICT (key) DO NOTHING;
