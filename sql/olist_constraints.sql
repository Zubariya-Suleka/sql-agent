-- Keys and indexes, added after the bulk load. A failure here means the data is not what
-- the schema assumes, which is worth knowing before anyone writes gold SQL against it.

ALTER TABLE olist.customers ADD PRIMARY KEY (customer_id);
ALTER TABLE olist.orders ADD PRIMARY KEY (order_id);
ALTER TABLE olist.products ADD PRIMARY KEY (product_id);
ALTER TABLE olist.sellers ADD PRIMARY KEY (seller_id);
ALTER TABLE olist.product_category_name_translation ADD PRIMARY KEY (product_category_name);
ALTER TABLE olist.order_items ADD PRIMARY KEY (order_id, order_item_id);
ALTER TABLE olist.order_payments ADD PRIMARY KEY (order_id, payment_sequential);
-- review_id alone is not unique: some reviews are attached to several orders.
ALTER TABLE olist.order_reviews ADD PRIMARY KEY (review_id, order_id);
-- geolocation has no key: a zip code prefix has many rows.

ALTER TABLE olist.orders ADD FOREIGN KEY (customer_id) REFERENCES olist.customers;
ALTER TABLE olist.order_items ADD FOREIGN KEY (order_id) REFERENCES olist.orders;
ALTER TABLE olist.order_items ADD FOREIGN KEY (product_id) REFERENCES olist.products;
ALTER TABLE olist.order_items ADD FOREIGN KEY (seller_id) REFERENCES olist.sellers;
ALTER TABLE olist.order_payments ADD FOREIGN KEY (order_id) REFERENCES olist.orders;
ALTER TABLE olist.order_reviews ADD FOREIGN KEY (order_id) REFERENCES olist.orders;
-- No foreign key from products to the translation table: some categories have no
-- English name, and some products have no category at all.

-- Join and filter columns the questions use most.
CREATE INDEX ON olist.orders (customer_id);
CREATE INDEX ON olist.orders (order_purchase_timestamp);
CREATE INDEX ON olist.order_items (product_id);
CREATE INDEX ON olist.order_items (seller_id);
CREATE INDEX ON olist.order_reviews (order_id);
CREATE INDEX ON olist.customers (customer_unique_id);
CREATE INDEX ON olist.products (product_category_name);
CREATE INDEX ON olist.geolocation (geolocation_zip_code_prefix);

ANALYZE;
