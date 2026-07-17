"""Schema migrations.

Applies every .sql file in postgres/migrations, in filename order, exactly once,
recording what has run in the schema_migrations table. bot.py runs this before it
starts, and it can also be run by hand against any database with:

    uv run -m utils.migrate

To change the schema, add a new numbered file to postgres/migrations. Never edit a
file that has already been applied -- the runner only tracks filenames, so the edit
would silently never reach production.
"""

import asyncio
from pathlib import Path

import psycopg

from utils import db

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "postgres" / "migrations"

# Scopes the advisory lock. Any constant works as long as nothing else in the
# database picks the same one.
_LOCK_KEY = 4867209


async def run_migrations():
    """Apply any migrations the database hasn't seen yet.

    Uses its own connection rather than the shared pool, so it can run before the
    bot's event loop exists.
    """
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise RuntimeError(f"No migrations found in {MIGRATIONS_DIR}")

    conn = await psycopg.AsyncConnection.connect(db.get_db_conninfo(), autocommit=True)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # Held for the length of the session, so two instances deploying at once
        # can't both try to apply the same file.
        await conn.execute("SELECT pg_advisory_lock(%s);", (_LOCK_KEY,))
        try:
            cur = await conn.execute("SELECT version FROM schema_migrations;")
            applied = {row[0] for row in await cur.fetchall()}

            pending = [path for path in files if path.name not in applied]
            if not pending:
                print(f"[migrations] up to date ({len(applied)} applied)")
                return

            for path in pending:
                # DDL is transactional in Postgres, so a migration that fails
                # partway leaves nothing behind and stays unrecorded.
                async with conn.transaction():
                    await conn.execute(path.read_text())
                    await conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s);",
                        (path.name,),
                    )
                print(f"[migrations] applied {path.name}")
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s);", (_LOCK_KEY,))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
