"""The agent's tools: OpenAI function definitions and what each one returns.

Results are compact text (rows as CSV): everything a tool returns is re-sent to the model
on every later step, so every token counts against the rate limits.
"""

import csv
import datetime as dt
import io
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import psycopg

from sql_agent.db import Database, QueryResult
from sql_agent.guard import MAX_ROWS, SqlRejected, check_sql

MAX_CELL_CHARS = 120

STATUSES = ["answered", "cannot_answer", "needs_clarification"]


def _function(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


TOOL_DEFINITIONS = [
    _function(
        "list_tables",
        "List the tables in the database, with a one-line description of each.",
        {},
        [],
    ),
    _function(
        "describe_table",
        "Show one table's columns (name, type, description) and 3 sample rows.",
        {"table": {"type": "string", "description": "A table name from list_tables."}},
        ["table"],
    ),
    _function(
        "run_sql",
        f"Run one read-only PostgreSQL SELECT. Returns at most {MAX_ROWS} rows as CSV. "
        "Errors come back as text: fix the query and call run_sql again.",
        {"query": {"type": "string", "description": "A single SELECT statement."}},
        ["query"],
    ),
    _function(
        "submit_answer",
        "Submit the final answer. Call it exactly once, as the last step.",
        {
            "status": {"type": "string", "enum": STATUSES},
            "sql": {
                "type": "string",
                "description": "The SELECT whose result answers the question; "
                "empty unless status is answered.",
            },
            "answer": {
                "type": "string",
                "description": "Short direct answer, or what is unclear or missing.",
            },
            "explanation": {
                "type": "string",
                "description": "How the SQL answers the question, in plain words.",
            },
        },
        ["status", "sql", "answer", "explanation"],
    ),
]


def _cell(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, dt.datetime):
        text = value.isoformat(sep=" ")
    elif isinstance(value, Decimal | float):
        text = format(value, "f") if isinstance(value, Decimal) else repr(value)
    else:
        text = str(value)
    text = " ".join(text.split())  # newlines in review comments would break the CSV view
    return text if len(text) <= MAX_CELL_CHARS else text[: MAX_CELL_CHARS - 1] + "…"


def format_rows(result: QueryResult) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(result.columns)
    writer.writerows([_cell(v) for v in row] for row in result.rows)
    return out.getvalue().rstrip("\n")


@dataclass
class ToolResult:
    """`text` goes to the model; `details` go to the trace."""

    text: str
    details: dict[str, Any] = field(default_factory=dict)
    error: bool = False


class ToolBox:
    def __init__(self, db: Database) -> None:
        self._db = db

    def call(self, name: str, raw_arguments: str | None) -> ToolResult:
        try:
            args = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            return ToolResult(f"ERROR: arguments are not valid JSON ({exc.msg})", error=True)
        if not isinstance(args, dict):
            return ToolResult("ERROR: arguments must be a JSON object", error=True)
        if name == "list_tables":
            return self.list_tables()
        if name == "describe_table":
            return self.describe_table(str(args.get("table", "")))
        if name == "run_sql":
            return self.run_sql(str(args.get("query", "")))
        return ToolResult(f"ERROR: unknown tool {name!r}", error=True)

    def list_tables(self) -> ToolResult:
        lines = [f"{name}: {description or ''}" for name, description in self._db.list_tables()]
        return ToolResult("\n".join(lines))

    def describe_table(self, table: str) -> ToolResult:
        info = self._db.describe_table(table.strip().lower())
        if info is None:
            return ToolResult(
                f"ERROR: no table named {table!r}; call list_tables to see the tables",
                error=True,
            )
        lines = [f"table {info.name} (~{info.approx_rows:,} rows): {info.description or ''}"]
        lines.append("columns:")
        for col in info.columns:
            null = "" if col.nullable else " NOT NULL"
            note = f"  -- {col.description}" if col.description else ""
            lines.append(f"  {col.name} {col.type}{null}{note}")
        lines.append(f"sample rows:\n{format_rows(info.sample)}")
        return ToolResult("\n".join(lines))

    def run_sql(self, query: str) -> ToolResult:
        try:
            checked = check_sql(query)
        except SqlRejected as exc:
            return ToolResult(f"REJECTED: {exc}", {"query": query, "rejected": str(exc)}, True)
        details: dict[str, Any] = {"query": query, "executed": checked.sql}
        try:
            result = self._db.query(checked.sql)
        except psycopg.errors.QueryCanceled:
            details["error"] = "statement timeout"
            return ToolResult(
                "ERROR: the query was cancelled after 5 s (statement timeout). Make it "
                "cheaper: filter earlier, aggregate before joining, avoid large cross joins.",
                details,
                True,
            )
        except psycopg.Error as exc:
            message = (exc.diag.message_primary or str(exc)).strip()
            hint = f" HINT: {exc.diag.message_hint}" if exc.diag.message_hint else ""
            details["error"] = message
            return ToolResult(f"ERROR: {message}{hint}", details, True)

        count = len(result.rows)
        details["row_count"] = count
        if count == 0:
            return ToolResult("(0 rows)", details)
        note = f"({count} rows)"
        if checked.limited and count >= MAX_ROWS:
            note = f"({count} rows: the {MAX_ROWS}-row limit was reached; there may be more)"
        return ToolResult(f"{format_rows(result)}\n{note}", details)
