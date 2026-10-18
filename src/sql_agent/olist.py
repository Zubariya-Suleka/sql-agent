"""The Olist tables and the CSV each one is loaded from."""

SCHEMA = "olist"

# Table name -> CSV file in the Kaggle download (olistbr/brazilian-ecommerce).
# Load order matters only for readability: constraints are added after all loads.
TABLES: dict[str, str] = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "product_category_name_translation": "product_category_name_translation.csv",
}
