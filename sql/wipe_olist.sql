BEGIN;
TRUNCATE raw.olist_orders, raw.olist_order_items, raw.olist_order_payments, raw.olist_order_reviews, raw.olist_customers, raw.olist_sellers, raw.olist_products, raw.olist_geolocation, raw.olist_category_translation RESTART IDENTITY;
DELETE FROM dwh.fact_price_snapshot WHERE product_key IN (SELECT product_key FROM dwh.dim_product WHERE source_key = (SELECT source_key FROM dwh.dim_source WHERE source_name = 'olist_csv'));
DELETE FROM dwh.dim_product WHERE source_key = (SELECT source_key FROM dwh.dim_source WHERE source_name = 'olist_csv');
DELETE FROM dwh.rejected_records WHERE source_name = 'olist_csv';
COMMIT;