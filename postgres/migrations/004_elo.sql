-- Elo system: per-game elo rating, seeded from rank, updated on each declared winner.

CREATE TABLE IF NOT EXISTS profile_elo (
    discordid BIGINT NOT NULL,
    game TEXT NOT NULL,
    elo NUMERIC NOT NULL,
    games_played INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (discordid, game)
);