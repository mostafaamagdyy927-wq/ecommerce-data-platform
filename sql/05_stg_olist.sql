-- 05_stg_olist.sql
-- Staging layer for Olist: typed + de-duplicated VIEWS on top of raw.olist_*.
-- Raw is never modified. Safe to run many times (CREATE OR REPLACE).

CREATE SCHEMA IF NOT EXISTS stg;

-- Safe casts: bad text becomes NULL instead of crashing the whole run.
CREATE OR REPLACE FUNCTION stg.to_num(t TEXT) RETURNS NUMERIC
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN btrim($1) ~ '^-?[0-9]+(\.[0-9]+)?$' THEN btrim($1)::numeric END
$$;

CREATE OR REPLACE FUNCTION stg.to_ts(t TEXT) RETURNS TIMESTAMP
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN btrim($1) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}( [0-9]{2}:[0-9]{2}:[0-9]{2})?$'
                THEN btrim($1)::timestamp END
$$;

-- Category translation (Portuguese -> English)
CREATE OR REPLACE VIEW stg.olist_category_translation AS
SELECT DISTINCT ON (product_category_name)
       btrim(product_category_name)         AS category_pt,
       NULLIF(btrim(product_category_name_english), '') AS category_en
FROM raw.olist_category_translation
WHERE NULLIF(btrim(product_category_name), '') IS NOT NULL
ORDER BY product_category_name, ingested_at DESC, id DESC;

-- Products
CREATE OR REPLACE VIEW stg.olist_products AS
SELECT DISTINCT ON (product_id)
       btrim(product_id)                         AS product_id,
       NULLIF(btrim(product_category_name), '')  AS category_pt,
       stg.to_num(product_weight_g)              AS weight_g,
       stg.to_num(product_length_cm)             AS length_cm,
       stg.to_num(product_height_cm)             AS height_cm,
       stg.to_num(product_width_cm)              AS width_cm
FROM raw.olist_products
WHERE NULLIF(btrim(product_id), '') IS NOT NULL
ORDER BY product_id, ingested_at DESC, id DESC;

-- Orders
CREATE OR REPLACE VIEW stg.olist_orders AS
SELECT DISTINCT ON (order_id)
       btrim(order_id)                              AS order_id,
       btrim(customer_id)                           AS customer_id,
       lower(btrim(order_status))                   AS order_status,
       stg.to_ts(order_purchase_timestamp)          AS purchased_at,
       stg.to_ts(order_delivered_customer_date)     AS delivered_at
FROM raw.olist_orders
WHERE NULLIF(btrim(order_id), '') IS NOT NULL
ORDER BY order_id, ingested_at DESC, id DESC;

-- Order items (keeps raw id + batch_id so rejects can point back to the raw row)
CREATE OR REPLACE VIEW stg.olist_order_items AS
SELECT DISTINCT ON (order_id, order_item_id)
       id                                AS raw_id,
       batch_id,
       btrim(order_id)                   AS order_id,
       btrim(order_item_id)              AS order_item_id,
       btrim(product_id)                 AS product_id,
       btrim(seller_id)                  AS seller_id,
       stg.to_num(price)                 AS price,
       stg.to_num(freight_value)         AS freight_value
FROM raw.olist_order_items
WHERE NULLIF(btrim(order_id), '') IS NOT NULL
ORDER BY order_id, order_item_id, ingested_at DESC, id DESC;

-- Reviews (one score per review)
CREATE OR REPLACE VIEW stg.olist_order_reviews AS
SELECT DISTINCT ON (review_id, order_id)
       btrim(review_id)                  AS review_id,
       btrim(order_id)                   AS order_id,
       CASE WHEN stg.to_num(review_score) BETWEEN 1 AND 5
            THEN stg.to_num(review_score) END AS review_score
FROM raw.olist_order_reviews
WHERE NULLIF(btrim(order_id), '') IS NOT NULL
ORDER BY review_id, order_id, ingested_at DESC, id DESC;
