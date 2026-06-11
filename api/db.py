import os
import psycopg2
import psycopg2.extras

DSN = os.environ.get("WAREHOUSE_DSN",
    "host=localhost port=5432 dbname=warehouse user=postgres password=postgres")


def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    with psycopg2.connect(DSN) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def execute(sql: str, params: tuple = ()) -> None:
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
