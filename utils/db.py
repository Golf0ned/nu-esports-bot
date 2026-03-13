from contextlib import asynccontextmanager
import os

import psycopg_pool

from utils import config


def get_db_conninfo():
    """Get database connection info from Railway env vars or local secrets."""
    # Check if running on Railway
    if os.getenv("RAILWAY_ENVIRONMENT"):
        # Use Railway's auto-generated Postgres environment variables
        return " ".join([
            f"host={os.getenv('PGHOST')}",
            f"port={os.getenv('PGPORT')}",
            f"dbname={os.getenv('PGDATABASE')}",
            f"user={os.getenv('PGUSER')}",
            f"password={os.getenv('PGPASSWORD')}",
        ])
    else:
        # Use local secrets.yaml
        DB_INFO = config.secrets["database"]
        return " ".join(
            [f"{key}={DB_INFO[key]}" for key in ["host", "port", "dbname", "user", "password"]]
        )


pool = psycopg_pool.AsyncConnectionPool(conninfo=get_db_conninfo(), open=False)


async def open_pool():
    await pool.open()


@asynccontextmanager
async def cursor():
    async with pool.connection() as conn:
        try:
            async with conn.cursor() as cur:
                yield cur
                await conn.commit()
        except Exception as e:
            await conn.rollback()
            raise e
        finally:
            await conn.close()


async def fetch_one(sql, parameters=None):
    async with cursor() as cur:
        await cur.execute(sql, parameters)
        result = await cur.fetchone()
    return result


async def fetch_all(sql, parameters=None):
    async with cursor() as cur:
        await cur.execute(sql, parameters)
        result = await cur.fetchall()
    return result


async def perform_one(sql, parameters=None):
    async with cursor() as cur:
        await cur.execute(sql, parameters)


async def perform_many(sql, parameters):
    async with cursor() as cur:
        await cur.executemany(sql, parameters)
