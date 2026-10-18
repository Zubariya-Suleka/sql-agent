"""SQL guard: only one read-only SELECT over the olist tables reaches the database.

agent_ro can only read and is cut off after 5 s, so the database is safe either way. The
guard is the layer in front of it: it rejects everything else up front with a reason the
model can act on, and caps how many rows a query can return.

What runs is the guard's own rendering of the parsed query, not the model's text, so the
statement that was checked is exactly the statement that executes.
"""

import logging
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from sql_agent.olist import SCHEMA, TABLES

MAX_ROWS = 100

# sqlglot logs a warning for syntax it can't parse (e.g. VACUUM); the guard reports it.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

# Anything that writes, locks rows, changes settings or runs a raw command. Searched for
# anywhere in the tree: a DELETE can hide inside a CTE of an otherwise normal SELECT.
_FORBIDDEN_NODES: dict[type[exp.Expression], str] = {
    exp.Insert: "INSERT",
    exp.Update: "UPDATE",
    exp.Delete: "DELETE",
    exp.Merge: "MERGE",
    exp.Create: "CREATE",
    exp.Drop: "DROP",
    exp.Alter: "ALTER",
    exp.TruncateTable: "TRUNCATE",
    exp.Copy: "COPY",
    exp.Set: "SET",
    exp.Command: "a raw command",
    exp.Transaction: "transaction control",
    exp.Commit: "transaction control",
    exp.Rollback: "transaction control",
    exp.Into: "SELECT ... INTO (it creates a table)",
    exp.Lock: "SELECT ... FOR UPDATE/SHARE (it locks rows)",
}

# Server functions that sleep, read files, change settings, signal other sessions or run
# SQL from a string. Analytics never needs them.
_FORBIDDEN_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink")
_FORBIDDEN_FUNCTIONS = {"set_config"}
_FORBIDDEN_FUNCTION_SUFFIXES = ("_to_xml", "_to_xmlschema", "_to_xml_and_xmlschema")


class SqlRejected(ValueError):
    """The query was not run. The message says why, in words a model can act on."""


@dataclass(frozen=True)
class CheckedSql:
    sql: str  # what to execute
    limited: bool  # a LIMIT was added or lowered to MAX_ROWS


def _function_name(node: exp.Func) -> str:
    return (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()


def _check_functions(tree: exp.Expression) -> None:
    for node in tree.find_all(exp.Func):
        name = _function_name(node)
        if (
            name in _FORBIDDEN_FUNCTIONS
            or name.startswith(_FORBIDDEN_FUNCTION_PREFIXES)
            or name.endswith(_FORBIDDEN_FUNCTION_SUFFIXES)
        ):
            raise SqlRejected(f"function {name}() is not allowed in agent queries")


def _check_tables(tree: exp.Expression) -> None:
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            continue  # a set-returning function in FROM, e.g. generate_series(); checked above
        name, schema = table.name.lower(), table.db.lower()
        if table.catalog or (schema and schema != SCHEMA):
            raise SqlRejected(
                f"{table.sql(dialect='postgres')} is outside schema {SCHEMA}; "
                "only the olist tables can be queried (call list_tables)"
            )
        if not schema and name in cte_names:
            continue
        if name not in TABLES:
            raise SqlRejected(f"unknown table {name!r}; call list_tables to see the tables")


def _apply_limit(tree: exp.Query, max_rows: int) -> tuple[exp.Query, bool]:
    limit = tree.args.get("limit")
    value = limit.expression if isinstance(limit, exp.Limit) else None
    if isinstance(value, exp.Literal) and value.is_int and int(value.this) <= max_rows:
        return tree, False
    return tree.limit(max_rows), True


def check_sql(query: str, *, max_rows: int = MAX_ROWS) -> CheckedSql:
    """Return the SQL to run, with LIMIT at most `max_rows`, or raise SqlRejected."""
    if not query or not query.strip():
        raise SqlRejected("the query is empty")
    try:
        trees = [t for t in sqlglot.parse(query, dialect="postgres") if t is not None]
    except sqlglot.errors.ParseError as exc:
        # sqlglot's own description names its internal classes; where it failed is what
        # helps a model fix the query.
        detail = exc.errors[0] if exc.errors else {}
        near = f" near {detail['highlight']!r}" if detail.get("highlight") else ""
        where = f" (line {detail['line']}, column {detail['col']})" if detail.get("line") else ""
        raise SqlRejected(
            f"could not parse the SQL{near}{where}; send one valid PostgreSQL SELECT"
        ) from exc
    except sqlglot.errors.SqlglotError as exc:  # e.g. an unterminated string
        raise SqlRejected(f"could not parse the SQL: {str(exc).splitlines()[0]}") from exc

    if len(trees) != 1:
        raise SqlRejected(f"send exactly one statement, not {len(trees)}")
    tree = trees[0]

    for node in tree.walk():
        kind = _FORBIDDEN_NODES.get(type(node))
        if kind:
            raise SqlRejected(f"only read-only SELECT queries are allowed, not {kind}")
    if not isinstance(tree, exp.Query):
        raise SqlRejected("only SELECT queries are allowed")

    _check_functions(tree)
    _check_tables(tree)
    limited_tree, limited = _apply_limit(tree, max_rows)
    return CheckedSql(limited_tree.sql(dialect="postgres"), limited)
