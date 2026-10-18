"""Read-only access to the Olist database, as agent_ro.

The metadata queries here are the tools' own trusted SQL. Only SQL written by the model
goes through the guard (sql_agent.guard) first.
"""

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql

from sql_agent.olist import SCHEMA


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]


@dataclass
class Column:
    name: str
    type: str
    nullable: bool
    description: str | None


@dataclass
class TableInfo:
    name: str
    description: str | None
    approx_rows: int
    columns: list[Column]
    sample: QueryResult


class Database:
    def __init__(self, url: str, *, connect_timeout: int = 10) -> None:
        self._url = url
        self._connect_timeout = connect_timeout
        self._conn: psycopg.Connection | None = None

    def _connection(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            # autocommit: every statement is its own read-only transaction, so one failed
            # query never leaves the session stuck in an aborted transaction.
            self._conn = psycopg.connect(
                self._url, connect_timeout=self._connect_timeout, autocommit=True
            )
        return self._conn

    def query(self, statement: str | sql.Composable, params: Any = None) -> QueryResult:
        with self._connection().cursor() as cur:
            cur.execute(statement, params)
            if cur.description is None:
                return QueryResult([], [])
            return QueryResult([d.name for d in cur.description], cur.fetchall())

    def list_tables(self) -> list[tuple[str, str | None]]:
        result = self.query(
            """SELECT c.relname, obj_description(c.oid, 'pg_class')
               FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = %s AND c.relkind = 'r'
               ORDER BY c.relname""",
            (SCHEMA,),
        )
        return [(name, description) for name, description in result.rows]

    def describe_table(self, name: str, *, sample_rows: int = 3) -> TableInfo | None:
        """None if `name` is not a table in the schema."""
        found = self.query(
            """SELECT c.oid, obj_description(c.oid, 'pg_class'), c.reltuples::bigint
               FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = %s AND c.relname = %s AND c.relkind = 'r'""",
            (SCHEMA, name),
        )
        if not found.rows:
            return None
        oid, description, approx_rows = found.rows[0]
        columns = self.query(
            """SELECT a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull,
                      col_description(a.attrelid, a.attnum)
               FROM pg_attribute a
               WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped
               ORDER BY a.attnum""",
            (oid,),
        )
        sample = self.query(
            sql.SQL("SELECT * FROM {} LIMIT {}").format(
                sql.Identifier(SCHEMA, name), sql.Literal(sample_rows)
            )
        )
        return TableInfo(
            name=name,
            description=description,
            approx_rows=max(approx_rows, 0),
            columns=[Column(*row) for row in columns.rows],
            sample=sample,
        )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
