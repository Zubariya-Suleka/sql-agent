"""Load the Olist CSVs into schema `olist` and (re)create the read-only role `agent_ro`.

    uv run python scripts/load_olist.py data/raw

Runs as the owner role (ADMIN_DATABASE_URL) in one transaction: it drops and rebuilds the
schema, streams each CSV in with COPY, adds keys, indexes and comments, then grants
agent_ro SELECT on the schema and nothing else. Safe to re-run. The same script loads a
managed Postgres later (Week 6), where there are no Docker init scripts.
"""

import argparse
import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql

from sql_agent.config import get_settings
from sql_agent.olist import SCHEMA, TABLES

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
BOM = b"\xef\xbb\xbf"
CHUNK = 1 << 20


def csv_columns(path: Path) -> list[str]:
    """Column names from the CSV header, so COPY follows the file's own order."""
    with path.open("rb") as f:
        header = f.readline().removeprefix(BOM).decode("utf-8").strip()
    return [name.strip().strip('"') for name in header.split(",")]


def copy_csv(conn: psycopg.Connection, table: str, path: Path) -> int:
    statement = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true)").format(
        sql.Identifier(SCHEMA, table),
        sql.SQL(", ").join(map(sql.Identifier, csv_columns(path))),
    )
    with conn.cursor() as cur:
        with cur.copy(statement) as copy, path.open("rb") as f:
            # The translation CSV starts with a UTF-8 BOM; keep it out of the data.
            copy.write(f.read(CHUNK).removeprefix(BOM))
            while chunk := f.read(CHUNK):
                copy.write(chunk)
        return cur.rowcount


def create_agent_role(conn: psycopg.Connection, password: str) -> None:
    database = conn.execute("SELECT current_database()").fetchone()[0]
    conn.execute(
        """DO $$ BEGIN
               IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_ro') THEN
                   CREATE ROLE agent_ro;
               END IF;
           END $$"""
    )
    statements = [
        sql.SQL(
            "ALTER ROLE agent_ro WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
        ).format(sql.Literal(password)),
        sql.SQL("GRANT CONNECT ON DATABASE {} TO agent_ro").format(sql.Identifier(database)),
        # Temp tables are writable even in a read-only transaction; nobody here needs them.
        sql.SQL("REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)),
        sql.SQL("GRANT USAGE ON SCHEMA olist TO agent_ro"),
        sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA olist TO agent_ro"),
        # Defaults for every agent_ro session. The SQL guard additionally blocks SET and
        # set_config(), so the agent cannot switch these off.
        sql.SQL("ALTER ROLE agent_ro SET statement_timeout = '5s'"),
        sql.SQL("ALTER ROLE agent_ro SET default_transaction_read_only = on"),
        sql.SQL("ALTER ROLE agent_ro SET search_path = olist"),
    ]
    for statement in statements:
        conn.execute(statement)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("raw_dir", type=Path, help="folder with the 9 Olist CSVs")
    args = parser.parse_args()

    missing = [name for name in TABLES.values() if not (args.raw_dir / name).is_file()]
    if missing:
        sys.exit(f"missing in {args.raw_dir}: {', '.join(missing)}")

    settings = get_settings()
    started = time.perf_counter()
    with psycopg.connect(
        settings.admin_database_url.get_secret_value(), connect_timeout=10
    ) as conn:
        conn.execute((SQL_DIR / "olist_schema.sql").read_text(encoding="utf-8"))
        for table, filename in TABLES.items():
            t0 = time.perf_counter()
            rows = copy_csv(conn, table, args.raw_dir / filename)
            print(f"  {table:<36} {rows:>9,} rows  {time.perf_counter() - t0:5.1f}s")
        print("  keys, indexes, statistics ...")
        conn.execute((SQL_DIR / "olist_constraints.sql").read_text(encoding="utf-8"))
        conn.execute((SQL_DIR / "olist_comments.sql").read_text(encoding="utf-8"))
        create_agent_role(conn, settings.agent_ro_password.get_secret_value())
        # Leaving the `with` block commits: all of it lands, or none of it.
    print(f"loaded schema {SCHEMA} in {time.perf_counter() - started:.0f}s")


if __name__ == "__main__":
    main()
