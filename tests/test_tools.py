import datetime as dt
from decimal import Decimal

import psycopg
import pytest

from sql_agent.config import get_settings
from sql_agent.db import Database, QueryResult
from sql_agent.guard import MAX_ROWS
from sql_agent.tools import TOOL_DEFINITIONS, ToolBox, format_rows


def test_tool_definitions_cover_the_plan():
    names = [t["function"]["name"] for t in TOOL_DEFINITIONS]
    assert names == ["list_tables", "describe_table", "run_sql", "submit_answer"]
    final = TOOL_DEFINITIONS[-1]["function"]["parameters"]
    assert set(final["required"]) == {"status", "sql", "answer", "explanation"}


def test_rows_render_as_compact_csv():
    result = QueryResult(
        ["id", "price", "at", "comment", "note"],
        [
            (1, Decimal("58.90"), dt.datetime(2017, 9, 19, 9, 45, 35), "line one\nline two", None),
            (2, Decimal("1.00"), None, "x" * 500, "ok"),
        ],
    )
    lines = format_rows(result).splitlines()
    assert lines[0] == "id,price,at,comment,note"
    assert lines[1] == "1,58.90,2017-09-19 09:45:35,line one line two,NULL"
    assert lines[2].endswith("…,ok")
    assert len(lines) == 3  # newlines inside values never split a row


@pytest.fixture(scope="module")
def tools():
    db = Database(get_settings().database_url.get_secret_value(), connect_timeout=3)
    try:
        db.query("SELECT 1")
    except psycopg.OperationalError:
        pytest.skip("Olist Postgres is not running: just db up, then just load")
    yield ToolBox(db)
    db.close()


def test_list_tables_shows_every_table_with_its_description(tools):
    lines = tools.list_tables().text.splitlines()
    assert len(lines) == 9
    assert any(line.startswith("orders: One row per order") for line in lines)


def test_describe_table_shows_columns_comments_and_samples(tools):
    text = tools.describe_table("orders").text
    assert text.startswith("table orders (~")
    assert "order_estimated_delivery_date timestamp without time zone NOT NULL" in text
    assert "Late = delivered after this date" in text
    assert "sample rows:\norder_id,customer_id" in text


def test_describe_unknown_table_is_an_error_for_the_model(tools):
    result = tools.describe_table("users")
    assert result.error and "call list_tables" in result.text


def test_run_sql_returns_csv_and_a_row_count(tools):
    result = tools.run_sql("SELECT order_status, count(*) FROM orders GROUP BY 1 ORDER BY 2 DESC")
    assert not result.error
    assert result.text.startswith("order_status,count\ndelivered,96478")
    assert result.text.endswith("(8 rows)")
    assert result.details["row_count"] == 8


def test_run_sql_says_when_the_row_limit_was_hit(tools):
    result = tools.run_sql("SELECT order_id FROM orders")
    assert f"the {MAX_ROWS}-row limit was reached" in result.text
    assert result.details["executed"].endswith(f"LIMIT {MAX_ROWS}")


def test_rejected_and_failing_queries_come_back_as_text(tools):
    rejected = tools.run_sql("DELETE FROM orders")
    assert rejected.error and rejected.text.startswith("REJECTED:")

    failing = tools.run_sql("SELECT no_such_column FROM orders")
    assert failing.error and failing.text.startswith("ERROR:")
    assert "no_such_column" in failing.text


def test_runaway_queries_are_cancelled_with_advice(tools):
    result = tools.run_sql("SELECT count(*) FROM geolocation a, geolocation b")
    assert result.error
    assert "cancelled after 5 s" in result.text
