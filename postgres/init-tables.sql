DROP TABLE IF EXISTS users;

CREATE TABLE users
(
    discordid BIGINT PRIMARY KEY,
    points BIGINT DEFAULT 0
);

