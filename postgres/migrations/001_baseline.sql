-- Baseline: the schema as it existed before migrations were introduced.
--
-- Databases that predate the migration runner (production, and any local volume
-- created from the old init-tables.sql) already have these tables, so every
-- statement here has to be a no-op against them. Only a brand new database
-- actually creates anything.

CREATE TABLE IF NOT EXISTS users
(
    discordid BIGINT PRIMARY KEY,
    points BIGINT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reservations
(
    id SERIAL PRIMARY KEY,
    team VARCHAR(50) NOT NULL,
    pcs INTEGER[] NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    manager VARCHAR(100) NOT NULL,
    is_prime_time BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
