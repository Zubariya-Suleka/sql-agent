-- Descriptions the agent reads through list_tables / describe_table. They state the traps
-- in this dataset plainly: a model can only avoid what the schema tells it about.

COMMENT ON SCHEMA olist IS 'Olist Brazilian e-commerce marketplace orders, 2016-09 to 2018-10. Amounts are in BRL.';

COMMENT ON TABLE olist.customers IS 'One row per order''s customer record. customer_id is per order; customer_unique_id identifies the person across orders.';
COMMENT ON COLUMN olist.customers.customer_id IS 'Per-order customer key (joins orders.customer_id). The same person gets a new customer_id on every order.';
COMMENT ON COLUMN olist.customers.customer_unique_id IS 'Stable id of the person across orders: use it to count unique or repeat customers.';
COMMENT ON COLUMN olist.customers.customer_zip_code_prefix IS 'First 5 digits of the zip code, as text with leading zeros.';
COMMENT ON COLUMN olist.customers.customer_state IS 'Two-letter Brazilian state code, e.g. SP, RJ, MG.';

COMMENT ON TABLE olist.geolocation IS 'Zip code prefixes with latitude/longitude. Several rows per prefix: not unique, aggregate before joining.';

COMMENT ON TABLE olist.orders IS 'One row per order: status and the purchase, approval, carrier hand-over, delivery and estimated delivery timestamps.';
COMMENT ON COLUMN olist.orders.order_status IS 'delivered, shipped, canceled, unavailable, invoiced, processing, created or approved.';
COMMENT ON COLUMN olist.orders.order_purchase_timestamp IS 'When the customer placed the order. Use it for "orders in <month/year>".';
COMMENT ON COLUMN olist.orders.order_delivered_customer_date IS 'When the customer received the order; NULL if it was never delivered.';
COMMENT ON COLUMN olist.orders.order_estimated_delivery_date IS 'Delivery date promised at purchase. Late = delivered after this date.';

COMMENT ON TABLE olist.order_items IS 'One row per item in an order (order_item_id 1, 2, ...): product, seller, price and freight. Joining it to orders repeats each order once per item.';
COMMENT ON COLUMN olist.order_items.price IS 'Item price in BRL, excluding freight.';
COMMENT ON COLUMN olist.order_items.freight_value IS 'Freight for this item in BRL; an order''s freight is the sum over its items.';
COMMENT ON COLUMN olist.order_items.shipping_limit_date IS 'Deadline for the seller to hand the item to the carrier.';

COMMENT ON TABLE olist.order_payments IS 'Payments per order. One order can be paid in several parts (payment_sequential 1, 2, ...).';
COMMENT ON COLUMN olist.order_payments.payment_type IS 'credit_card, boleto, voucher, debit_card or not_defined.';
COMMENT ON COLUMN olist.order_payments.payment_installments IS 'Number of installments the customer chose.';
COMMENT ON COLUMN olist.order_payments.payment_value IS 'Amount of this payment in BRL.';

COMMENT ON TABLE olist.order_reviews IS 'Customer reviews: a 1-5 score with an optional title and comment in Portuguese.';
COMMENT ON COLUMN olist.order_reviews.review_id IS 'Not unique on its own: some reviews are attached to several orders.';
COMMENT ON COLUMN olist.order_reviews.review_score IS '1 (worst) to 5 (best).';

COMMENT ON TABLE olist.products IS 'Product catalogue: Portuguese category name and physical dimensions. No names, brands or costs.';
COMMENT ON COLUMN olist.products.product_category_name IS 'Category in Portuguese; NULL for some products. For English names join product_category_name_translation (some categories have no translation).';
COMMENT ON COLUMN olist.products.product_name_lenght IS 'Length of the product name in characters (the column name is misspelled in the source data).';
COMMENT ON COLUMN olist.products.product_description_lenght IS 'Length of the product description in characters (misspelled in the source data).';

COMMENT ON TABLE olist.sellers IS 'Sellers on the marketplace, with zip code prefix, city and state.';

COMMENT ON TABLE olist.product_category_name_translation IS 'Portuguese product category name to English name.';
