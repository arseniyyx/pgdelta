import os

import psycopg
import pytest

FROM_DSN = os.environ.get(
    "PGDELTA_FROM_DSN", "postgresql://postgres:postgres@localhost:5432/pgdelta_src"
)
TO_DSN = os.environ.get(
    "PGDELTA_TO_DSN", "postgresql://postgres:postgres@localhost:5432/pgdelta_dst"
)


def _reset(dsn: str, sql: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
        cur.execute("CREATE SCHEMA public")
        for statement in (s.strip() for s in sql.split(";")):
            if statement:
                cur.execute(statement)


@pytest.fixture
def from_dsn():
    return FROM_DSN


@pytest.fixture
def to_dsn():
    return TO_DSN


@pytest.fixture
def setup_schemas():
    def _setup(src_sql: str, dst_sql: str) -> None:
        _reset(FROM_DSN, src_sql)
        _reset(TO_DSN, dst_sql)

    return _setup
