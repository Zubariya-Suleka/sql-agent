"""Integration tests against the local Olist Postgres, as the agent's role.

Skipped when the database isn't running (e.g. in CI): `just db up`, then `just load`.
"""

import psycopg
import pytest
from psycopg import errors, sql

from sql_agent.config import get_settings
from sql_agent.olist import SCHEMA, TABLES


@pytest.fixture(scope="module")
def conn():
    try:
        conn = psycopg.connect(get_settings().database_url.get_secret_value(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Olist Postgres is not running: just db up, then just load")
    yield conn
    conn.close()


@pytest.mark.parametrize("table", TABLES)
def test_every_table_is_loaded(conn, table):
    query = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(SCHEMA, table))
    assert conn.execute(query).fetchone()[0] > 0
    conn.rollback()


def test_agent_sessions_start_read_only_with_a_timeout(conn):
    user, timeout, read_only = conn.execute(
        "SELECT current_user, current_setting('statement_timeout'),"
        " current_setting('default_transaction_read_only')"
    ).fetchone()
    assert (user, timeout, read_only) == ("agent_ro", "5s", "on")
    # search_path is olist, so bare table names work.
    assert conn.execute("SELECT count(*) FROM sellers").fetchone()[0] > 0
    conn.rollback()


def test_writes_fail_even_with_read_only_switched_off(conn):
    conn.execute("SET default_transaction_read_only = off")
    conn.commit()
    try:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("INSERT INTO sellers VALUES ('x', '00000', 'x', 'XX')")
    finally:
        conn.rollback()
        conn.execute("RESET default_transaction_read_only")
        conn.commit()


def test_long_queries_are_cancelled_after_5_seconds(conn):
    with pytest.raises(errors.QueryCanceled):
        conn.execute("SELECT pg_sleep(6)")
    conn.rollback()
