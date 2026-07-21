-- Profile system: bios, per-game rank/role/mains, and win/loss tracking.

CREATE TABLE IF NOT EXISTS profiles
(
    discordid BIGINT PRIMARY KEY,
    bio TEXT,
    picture_url TEXT,
    thumbnail_url TEXT,
    tag TEXT,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS profile_stats (
    discordid BIGINT NOT NULL,
    game TEXT NOT NULL,
    rank_value INT,
    rank_label TEXT,
    wins INT NOT NULL DEFAULT 0,
    losses INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (discordid, game)
);

CREATE TABLE IF NOT EXISTS profile_roles (
    discordid BIGINT NOT NULL,
    game TEXT NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY (discordid, game, role)
);

CREATE TABLE IF NOT EXISTS profile_mains (
    discordid BIGINT NOT NULL,
    game TEXT NOT NULL,
    main TEXT NOT NULL,
    PRIMARY KEY (discordid, game, main)
);

CREATE TABLE IF NOT EXISTS profile_primary_mains (
    discordid BIGINT NOT NULL,
    game TEXT NOT NULL,
    prime TEXT NOT NULL,
    PRIMARY KEY (discordid, game),
    FOREIGN KEY (discordid, game, prime) REFERENCES profile_mains (discordid, game, main) ON DELETE CASCADE
);