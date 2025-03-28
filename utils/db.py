import psycopg
import psycopg.pool

from utils import config


DB_INFO = config.secrets["database"]


__host = DB_INFO["host"]
__port = DB_INFO["port"]
__dbname = DB_INFO["dbname"]
__user = DB_INFO["user"]
__password = DB_INFO["password"]

__conninfo = f"host={__host} port={__port} dbname={__dbname} user={__user} password={__password}"
dbpool = psycopg.pool.AsyncConnectionPool(conninfo=__conninfo)

@contextmanager
async def cursor():
    with await dbpool.connection() as conn:
        with conn.cursor() as cur:
            try:
                yield cur
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                raise e
            finally:
                await conn.close()
