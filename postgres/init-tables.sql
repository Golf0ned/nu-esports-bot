DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS reservations;

CREATE TABLE users
(
    discordid BIGINT PRIMARY KEY,
    points BIGINT DEFAULT 0
);

CREATE TABLE reservations
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

CREATE TABLE profiles
(
    discordid BIGINT PRIMARY KEY,
    bio TEXT,
    picture_url TEXT,
    thumbnail_url TEXT,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE profile_stats (
    discordid BIGINT NOT NULL,
    game TEXT NOT NULL,
    rank_value INT,
    rank_label TEXT,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (discordid, game)
);

CREATE TABLE profile_roles (
    discordid BIGINT NOT NULL,
    game TEXT NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY (discordid, game, role)
);

CREATE TABLE profile_mains (
    discordid BIGINT NOT NULL,
    game TEXT NOT NULL,
    main TEXT NOT NULL,
    PRIMARY KEY (discordid, game, main)
);

CREATE TABLE profile_primary_mains (
    discordid BIGINT NOT NULL,
    game TEXT NOT NULL,
    prime TEXT NOT NULL,
    PRIMARY KEY (discordid, game),
    FOREIGN KEY (discordid, game, prime) REFERENCES profile_mains (discordid, game, main) ON DELETE CASCADE
);