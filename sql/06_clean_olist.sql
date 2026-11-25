-- 06_clean_olist.sql
-- Clean layer for Olist: stg.* views -> dwh.dim_source / dim_product / fact_price_snapshot.
-- Idempotent: running it again updates the same rows, never duplicates.
-- Needs 05_stg_olist.sql first.

BEGIN;

-- 1) Source
INSERT INTO dwh.dim_source (source_name, data_origin, description)
VALUES ('olist_csv', 'real_dataset',
        'Olist Brazilian e-commerce public dataset (Kaggle CSV). Prices are order-item sale prices in BRL.')
ON CONFLICT (source_name) DO NOTHING;

-- 2) Products
INSERT INTO dwh.dim_product
    (source_key, source_product_id, sku, category, category_label,
     brand, weight, width, height, depth)
SELECT s.source_key,
       p.product_id,
       p.product_id,
       COALESCE(t.category_en, p.category_pt, 'Unknown'),
       p.category_pt,
       'Unknown',                      -- Olist has no brand column
       p.weight_g,
       p.width_cm,
       p.height_cm,
       p.length_cm
FROM stg.olist_products p
LEFT JOIN stg.olist_category_translation t ON t.category_pt = p.category_pt
CROSS JOIN (SELECT source_key FROM dwh.dim_source WHERE source_name = 'olist_csv') s
ON CONFLICT (source_key, source_product_id) DO UPDATE
SET category       = EXCLUDED.category,
    category_label = EXCLUDED.category_label,
    weight         = EXCLUDED.weight,
    width          = EXCLUDED.width,
    height         = EXCLUDED.height,
    depth          = EXCLUDED.depth;

-- 3) Rejected items (kept, not silently dropped)
INSERT INTO dwh.rejected_records (source_name, batch_id, raw_id, reason, payload)
SELECT 'olist_csv', i.batch_id, i.raw_id,
       CASE
           WHEN i.price IS NULL OR i.price <= 0       THEN 'olist: invalid or missing price'
           WHEN o.order_id IS NULL                    THEN 'olist: order not found for item'
           WHEN o.purchased_at IS NULL                THEN 'olist: order has no valid purchase date'
           ELSE                                            'olist: product not found in products'
       END,
       jsonb_build_object('order_id', i.order_id, 'order_item_id', i.order_item_id,
                          'product_id', i.product_id, 'price', i.price)
FROM stg.olist_order_items i
LEFT JOIN stg.olist_orders   o ON o.order_id   = i.order_id
LEFT JOIN stg.olist_products p ON p.product_id = i.product_id
WHERE (i.price IS NULL OR i.price <= 0
       OR o.order_id IS NULL OR o.purchased_at IS NULL
       OR p.product_id IS NULL)
  AND NOT EXISTS (
        SELECT 1 FROM dwh.rejected_records r
        WHERE r.source_name = 'olist_csv' AND r.raw_id = i.raw_id AND r.batch_id = i.batch_id
          AND r.reason LIKE 'olist:%');

-- 4) Price snapshots: ONE ROW PER PRODUCT PER DAY (option A, no schema change).
--    price  = average item sale price that day (BRL)
--    rating = average review score of the orders that day
--    batch_id = 'olist_YYYYMMDD' so UNIQUE (product_key, batch_id) = one row per product per day
WITH order_rating AS (
    SELECT order_id, avg(review_score) AS score
    FROM stg.olist_order_reviews
    WHERE review_score IS NOT NULL
    GROUP BY order_id
),
daily AS (
    SELECT dp.product_key,
           o.purchased_at::date                         AS day,
           round(avg(i.price), 2)                       AS price,
           round(avg(r.score), 2)                       AS rating
    FROM stg.olist_order_items i
    JOIN stg.olist_orders o      ON o.order_id = i.order_id
    JOIN dwh.dim_source s        ON s.source_name = 'olist_csv'
    JOIN dwh.dim_product dp      ON dp.source_key = s.source_key
                                AND dp.source_product_id = i.product_id
    LEFT JOIN order_rating r     ON r.order_id = i.order_id
    WHERE i.price > 0
      AND o.purchased_at IS NOT NULL
      AND o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY dp.product_key, o.purchased_at::date
)
INSERT INTO dwh.fact_price_snapshot
    (product_key, batch_id, captured_at, captured_date, price, currency,
     discount_percentage, price_after_discount, rating, stock, availability_status)
SELECT product_key,
       'olist_' || to_char(day, 'YYYYMMDD'),
       day::timestamp AT TIME ZONE 'America/Sao_Paulo',
       day,
       price,
       'BRL',
       NULL, NULL,
       rating,
       NULL,
       'sold'
FROM daily
WHERE price > 0
ON CONFLICT (product_key, batch_id) DO UPDATE
SET price         = EXCLUDED.price,
    rating        = EXCLUDED.rating,
    captured_at   = EXCLUDED.captured_at,
    captured_date = EXCLUDED.captured_date;

COMMIT;
