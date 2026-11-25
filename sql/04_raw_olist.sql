CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.olist_orders (
    id          BIGSERIAL PRIMARY KEY,
    source_name TEXT        NOT NULL,
    batch_id    TEXT        NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_num     INTEGER     NOT NULL,
    order_id TEXT,
    customer_id TEXT,
    order_status TEXT,
    order_purchase_timestamp TEXT,
    order_approved_at TEXT,
    order_delivered_carrier_date TEXT,
    order_delivered_customer_date TEXT,
    order_estimated_delivery_date TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_olist_orders_batch_row
    ON raw.olist_orders (source_name, batch_id, row_num);

CREATE TABLE IF NOT EXISTS raw.olist_order_items (
    id          BIGSERIAL PRIMARY KEY,
    source_name TEXT        NOT NULL,
    batch_id    TEXT        NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_num     INTEGER     NOT NULL,
    order_id TEXT,
    order_item_id TEXT,
    product_id TEXT,
    seller_id TEXT,
    shipping_limit_date TEXT,
    price TEXT,
    freight_value TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_olist_order_items_batch_row
    ON raw.olist_order_items (source_name, batch_id, row_num);

CREATE TABLE IF NOT EXISTS raw.olist_order_payments (
    id          BIGSERIAL PRIMARY KEY,
    source_name TEXT        NOT NULL,
    batch_id    TEXT        NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_num     INTEGER     NOT NULL,
    order_id TEXT,
    payment_sequential TEXT,
    payment_type TEXT,
    payment_installments TEXT,
    payment_value TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_olist_order_payments_batch_row
    ON raw.olist_order_payments (source_name, batch_id, row_num);

CREATE TABLE IF NOT EXISTS raw.olist_order_reviews (
    id          BIGSERIAL PRIMARY KEY,
    source_name TEXT        NOT NULL,
    batch_id    TEXT        NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_num     INTEGER     NOT NULL,
    review_id TEXT,
    order_id TEXT,
    review_score TEXT,
    review_comment_title TEXT,
    review_comment_message TEXT,
    review_creation_date TEXT,
    review_answer_timestamp TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_olist_order_reviews_batch_row
    ON raw.olist_order_reviews (source_name, batch_id, row_num);

CREATE TABLE IF NOT EXISTS raw.olist_customers (
    id          BIGSERIAL PRIMARY KEY,
    source_name TEXT        NOT NULL,
    batch_id    TEXT        NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_num     INTEGER     NOT NULL,
    customer_id TEXT,
    customer_unique_id TEXT,
    customer_zip_code_prefix TEXT,
    customer_city TEXT,
    customer_state TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_olist_customers_batch_row
    ON raw.olist_customers (source_name, batch_id, row_num);

CREATE TABLE IF NOT EXISTS raw.olist_sellers (
    id          BIGSERIAL PRIMARY KEY,
    source_name TEXT        NOT NULL,
    batch_id    TEXT        NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_num     INTEGER     NOT NULL,
    seller_id TEXT,
    seller_zip_code_prefix TEXT,
    seller_city TEXT,
    seller_state TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_olist_sellers_batch_row
    ON raw.olist_sellers (source_name, batch_id, row_num);

CREATE TABLE IF NOT EXISTS raw.olist_products (
    id          BIGSERIAL PRIMARY KEY,
    source_name TEXT        NOT NULL,
    batch_id    TEXT        NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_num     INTEGER     NOT NULL,
    product_id TEXT,
    product_category_name TEXT,
    product_name_lenght TEXT,
    product_description_lenght TEXT,
    product_photos_qty TEXT,
    product_weight_g TEXT,
    product_length_cm TEXT,
    product_height_cm TEXT,
    product_width_cm TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_olist_products_batch_row
    ON raw.olist_products (source_name, batch_id, row_num);

CREATE TABLE IF NOT EXISTS raw.olist_geolocation (
    id          BIGSERIAL PRIMARY KEY,
    source_name TEXT        NOT NULL,
    batch_id    TEXT        NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_num     INTEGER     NOT NULL,
    geolocation_zip_code_prefix TEXT,
    geolocation_lat TEXT,
    geolocation_lng TEXT,
    geolocation_city TEXT,
    geolocation_state TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_olist_geolocation_batch_row
    ON raw.olist_geolocation (source_name, batch_id, row_num);

CREATE TABLE IF NOT EXISTS raw.olist_category_translation (
    id          BIGSERIAL PRIMARY KEY,
    source_name TEXT        NOT NULL,
    batch_id    TEXT        NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_num     INTEGER     NOT NULL,
    product_category_name TEXT,
    product_category_name_english TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_olist_category_translation_batch_row
    ON raw.olist_category_translation (source_name, batch_id, row_num);

-- Lookup indexes used by the transform
CREATE INDEX IF NOT EXISTS idx_raw_olist_items_order ON raw.olist_order_items (batch_id, order_id);
CREATE INDEX IF NOT EXISTS idx_raw_olist_items_product ON raw.olist_order_items (batch_id, product_id);
CREATE INDEX IF NOT EXISTS idx_raw_olist_orders_order ON raw.olist_orders (batch_id, order_id);
CREATE INDEX IF NOT EXISTS idx_raw_olist_products_product ON raw.olist_products (batch_id, product_id);
