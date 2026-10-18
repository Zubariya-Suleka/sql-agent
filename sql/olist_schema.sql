-- Olist Brazilian e-commerce dataset (Kaggle: olistbr/brazilian-ecommerce).
-- Column names are kept exactly as in the CSVs, typos included (product_name_lenght):
-- the agent has to cope with the schema as it really is.
-- Keys, indexes and comments are added after the bulk load (olist_constraints.sql,
-- olist_comments.sql): building them once at the end is much faster than per row.

DROP SCHEMA IF EXISTS olist CASCADE;
CREATE SCHEMA olist;

CREATE TABLE olist.customers (
    customer_id              text NOT NULL,
    customer_unique_id       text NOT NULL,
    customer_zip_code_prefix text NOT NULL,
    customer_city            text NOT NULL,
    customer_state           text NOT NULL
);

CREATE TABLE olist.geolocation (
    geolocation_zip_code_prefix text NOT NULL,
    geolocation_lat             double precision NOT NULL,
    geolocation_lng             double precision NOT NULL,
    geolocation_city            text NOT NULL,
    geolocation_state           text NOT NULL
);

CREATE TABLE olist.orders (
    order_id                      text NOT NULL,
    customer_id                   text NOT NULL,
    order_status                  text NOT NULL,
    order_purchase_timestamp      timestamp NOT NULL,
    order_approved_at             timestamp,
    order_delivered_carrier_date  timestamp,
    order_delivered_customer_date timestamp,
    order_estimated_delivery_date timestamp NOT NULL
);

CREATE TABLE olist.order_items (
    order_id            text NOT NULL,
    order_item_id       integer NOT NULL,
    product_id          text NOT NULL,
    seller_id           text NOT NULL,
    shipping_limit_date timestamp NOT NULL,
    price               numeric(10, 2) NOT NULL,
    freight_value       numeric(10, 2) NOT NULL
);

CREATE TABLE olist.order_payments (
    order_id             text NOT NULL,
    payment_sequential   integer NOT NULL,
    payment_type         text NOT NULL,
    payment_installments integer NOT NULL,
    payment_value        numeric(10, 2) NOT NULL
);

CREATE TABLE olist.order_reviews (
    review_id               text NOT NULL,
    order_id                text NOT NULL,
    review_score            integer NOT NULL,
    review_comment_title    text,
    review_comment_message  text,
    review_creation_date    timestamp NOT NULL,
    review_answer_timestamp timestamp NOT NULL
);

CREATE TABLE olist.products (
    product_id                 text NOT NULL,
    product_category_name      text,
    product_name_lenght        integer,
    product_description_lenght integer,
    product_photos_qty         integer,
    product_weight_g           integer,
    product_length_cm          integer,
    product_height_cm          integer,
    product_width_cm           integer
);

CREATE TABLE olist.sellers (
    seller_id              text NOT NULL,
    seller_zip_code_prefix text NOT NULL,
    seller_city            text NOT NULL,
    seller_state           text NOT NULL
);

CREATE TABLE olist.product_category_name_translation (
    product_category_name         text NOT NULL,
    product_category_name_english text NOT NULL
);
