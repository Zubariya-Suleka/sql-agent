import pytest

from sql_agent.guard import MAX_ROWS, SqlRejected, check_sql

ALLOWED = [
    "SELECT count(*) FROM orders",
    "select order_id from olist.orders where order_status = 'delivered'",
    "WITH late AS (SELECT * FROM orders WHERE order_delivered_customer_date"
    " > order_estimated_delivery_date) SELECT count(*) FROM late",
    "SELECT seller_id FROM sellers UNION ALL SELECT seller_id FROM order_items",
    "SELECT date_trunc('month', order_purchase_timestamp) AS m, count(*) FROM orders GROUP BY 1",
    "SELECT count(*) FILTER (WHERE review_score <= 2) FROM order_reviews",
    "SELECT price::int, rank() OVER (PARTITION BY seller_id ORDER BY price DESC) FROM order_items",
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY payment_value) FROM order_payments",
    "SELECT * FROM products WHERE product_category_name ILIKE '%moveis%'",
    "SELECT EXTRACT(year FROM order_purchase_timestamp), count(*) FROM orders GROUP BY 1",
    "SELECT n FROM generate_series(1, 3) AS g(n)",
    "SELECT 1;",  # a trailing semicolon is still one statement
]


@pytest.mark.parametrize("query", ALLOWED)
def test_read_only_queries_over_olist_are_allowed(query):
    assert check_sql(query).sql


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("INSERT INTO sellers VALUES ('x', '1', 'x', 'XX')", "INSERT"),
        ("UPDATE orders SET order_status = 'x'", "UPDATE"),
        ("DELETE FROM orders", "DELETE"),
        ("DROP TABLE orders", "DROP"),
        ("CREATE TABLE x (id int)", "CREATE"),
        ("ALTER TABLE orders ADD COLUMN x int", "ALTER"),
        ("TRUNCATE orders", "TRUNCATE"),
        ("COPY orders TO STDOUT", "COPY"),
        ("SET statement_timeout = 0", "SET"),
        ("VACUUM orders", "raw command"),
        ("GRANT SELECT ON orders TO public", "only SELECT"),
        ("BEGIN", "transaction"),
        ("WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d", "DELETE"),
        ("SELECT * INTO copy_of_orders FROM orders", "INTO"),
        ("SELECT * FROM orders FOR UPDATE", "FOR UPDATE"),
        ("SELECT 1; SELECT 2", "exactly one statement"),
        ("SELECT 1; DROP TABLE orders", "exactly one statement"),
        ("SELECT pg_sleep(10)", "pg_sleep"),
        ("SELECT set_config('statement_timeout', '0', false)", "set_config"),
        ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
        ("SELECT query_to_xml('select 1', true, true, '')", "query_to_xml"),
        ("SELECT lo_import('/etc/passwd')", "lo_import"),
        ("SELECT * FROM pg_catalog.pg_roles", "outside schema olist"),
        ("SELECT * FROM information_schema.tables", "outside schema olist"),
        ("SELECT * FROM public.anything", "outside schema olist"),
        ("SELECT * FROM users", "unknown table"),
        ("", "empty"),
        ("SELECT 'unterminated FROM orders", "could not parse"),
    ],
)
def test_everything_else_is_rejected_with_a_reason(query, reason):
    with pytest.raises(SqlRejected, match=reason):
        check_sql(query)


def test_syntax_errors_say_where_without_parser_internals():
    with pytest.raises(SqlRejected) as info:
        check_sql("SELEC * FROM orders")
    message = str(info.value)
    assert "near 'FROM'" in message
    assert "line 1" in message
    assert "sqlglot" not in message and "class" not in message


def test_cte_names_count_as_tables():
    check_sql("WITH big_sellers AS (SELECT seller_id FROM sellers) SELECT * FROM big_sellers")


def test_missing_limit_is_added():
    checked = check_sql("SELECT * FROM geolocation")
    assert checked.limited
    assert checked.sql.endswith(f"LIMIT {MAX_ROWS}")


def test_small_limit_is_kept_and_large_limit_is_capped():
    assert not check_sql("SELECT * FROM orders LIMIT 5").limited
    capped = check_sql("SELECT * FROM orders LIMIT 5000")
    assert capped.limited
    assert capped.sql.endswith(f"LIMIT {MAX_ROWS}")


def test_limit_applies_to_the_whole_union():
    checked = check_sql("SELECT seller_id FROM sellers UNION SELECT seller_id FROM order_items")
    assert checked.sql.endswith(f"LIMIT {MAX_ROWS}")
    assert checked.sql.count("LIMIT") == 1


def test_a_limit_inside_a_subquery_does_not_limit_the_outer_query():
    checked = check_sql("SELECT * FROM (SELECT * FROM orders LIMIT 5) AS t")
    assert checked.limited  # the outer query had no LIMIT of its own
