"""The guard runs its own rendering of the query, so that rendering must mean the same thing.

Each query here returns fewer than MAX_ROWS rows, so the added LIMIT cannot change the
result: original and rendered SQL must return identical rows. Skipped without the database.
"""

import psycopg
import pytest

from sql_agent.config import get_settings
from sql_agent.guard import check_sql

REALISTIC = [
    # time windows, late deliveries, joins, aggregates, windows, percentiles, casts
    """SELECT date_trunc('month', o.order_purchase_timestamp) AS month,
              round(sum(i.price + i.freight_value), 2) AS gmv
       FROM orders o JOIN order_items i USING (order_id)
       WHERE o.order_purchase_timestamp >= '2018-01-01'
         AND o.order_purchase_timestamp < '2018-07-01'
       GROUP BY 1 ORDER BY 1""",
    """SELECT c.customer_state,
              round(100.0 * count(*) FILTER (WHERE o.order_delivered_customer_date
                    > o.order_estimated_delivery_date) / count(*), 2) AS late_pct
       FROM orders o JOIN customers c USING (customer_id)
       WHERE o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL
       GROUP BY 1 ORDER BY 2 DESC, 1""",
    """WITH per_seller AS (
           SELECT seller_id, count(DISTINCT order_id) AS orders FROM order_items GROUP BY 1)
       SELECT seller_id, orders, rank() OVER (ORDER BY orders DESC) AS r
       FROM per_seller ORDER BY orders DESC, seller_id LIMIT 10""",
    """SELECT coalesce(t.product_category_name_english, p.product_category_name, 'unknown') AS cat,
              count(*) AS n
       FROM products p LEFT JOIN product_category_name_translation t USING (product_category_name)
       GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 15""",
    """SELECT payment_type,
              percentile_cont(0.5) WITHIN GROUP (ORDER BY payment_value) AS median_value,
              avg(payment_installments)::numeric(6, 2) AS avg_installments
       FROM order_payments GROUP BY 1 ORDER BY 1""",
    """SELECT EXTRACT(dow FROM order_purchase_timestamp)::int AS dow, count(*)
       FROM orders GROUP BY 1 ORDER BY 1""",
    """SELECT review_score, count(*) FROM order_reviews
       WHERE review_creation_date >= DATE '2018-01-01' - INTERVAL '30 days'
       GROUP BY 1 ORDER BY 1""",
    """SELECT count(DISTINCT customer_unique_id) FROM customers c
       WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id
                     AND o.order_status = 'canceled')""",
]


@pytest.fixture(scope="module")
def conn():
    try:
        conn = psycopg.connect(get_settings().database_url.get_secret_value(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Olist Postgres is not running: just db up, then just load")
    yield conn
    conn.close()


@pytest.mark.parametrize("query", REALISTIC)
def test_rendered_sql_returns_the_same_rows(conn, query):
    original = conn.execute(query).fetchall()
    rendered = conn.execute(check_sql(query).sql).fetchall()
    conn.rollback()
    assert original, "test query should return rows"
    assert rendered == original
