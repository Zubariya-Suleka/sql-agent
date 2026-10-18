"""Row counts per table, read as the agent's role, plus proof that the role is read-only.

    uv run python scripts/check_db.py

Exits 1 if any table is empty or agent_ro can do anything but read.
"""

import sys

import psycopg
from psycopg import sql

from sql_agent.config import get_settings
from sql_agent.olist import SCHEMA, TABLES


def must_fail(conn: psycopg.Connection, statement: str) -> str:
    """Run a statement that agent_ro must not be allowed to run; return why it failed."""
    try:
        conn.execute(statement)
    except psycopg.Error as exc:
        conn.rollback()
        return f"blocked ({type(exc).__name__})"
    conn.rollback()
    return "ALLOWED"


def main() -> None:
    url = get_settings().database_url.get_secret_value()
    problems = []
    with psycopg.connect(url, connect_timeout=10) as conn:
        user, timeout, read_only = conn.execute(
            "SELECT current_user, current_setting('statement_timeout'),"
            " current_setting('default_transaction_read_only')"
        ).fetchone()
        print(f"connected as {user}: statement_timeout={timeout}, read_only={read_only}\n")
        for table in TABLES:
            count = conn.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(SCHEMA, table))
            ).fetchone()[0]
            print(f"  {table:<36} {count:>9,}")
            if not count:
                problems.append(f"{table} is empty")
        conn.rollback()

        print()
        checks = {
            "insert a row": "INSERT INTO olist.sellers VALUES ('x', '00000', 'x', 'XX')",
            "create a table": "CREATE TABLE olist.scratch (id int)",
            "create a temp table": "CREATE TEMP TABLE scratch (id int)",
        }
        for label, statement in checks.items():
            outcome = must_fail(conn, statement)
            print(f"  {label:<26} {outcome}")
            if outcome == "ALLOWED":
                problems.append(f"agent_ro can {label}")

        # Read-only is only the first layer. With it switched off for the session (the SET
        # applies from the next transaction), missing privileges must still stop the write.
        conn.execute("SET default_transaction_read_only = off")
        conn.commit()
        outcome = must_fail(conn, "INSERT INTO olist.sellers VALUES ('x', '00000', 'x', 'XX')")
        print(f"  {'write with read-only off':<26} {outcome}")
        if outcome == "ALLOWED":
            problems.append("agent_ro can write once read-only is switched off")

    if timeout != "5s":
        problems.append(f"statement_timeout is {timeout}, expected 5s")
    if problems:
        sys.exit("\nPROBLEMS: " + "; ".join(problems))
    print("\nall checks passed")


if __name__ == "__main__":
    main()
