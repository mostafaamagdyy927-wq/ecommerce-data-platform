-- 08_clean_sources.sql
-- Registers the scraping source and creates one unified view over all sources.
-- Safe to run many times.

INSERT INTO dwh.dim_source (source_name, data_origin, description)
VALUES ('books_to_scrape', 'scraped',
        'books.toscrape.com scraped catalogue (demo site). Prices are in GBP.')
ON CONFLICT (source_name) DO NOTHING;

CREATE OR REPLACE VIEW dwh.v_price_history AS
SELECT s.source_name,
       s.data_origin,
       p.product_key,
       p.source_product_id,
       p.title,
       p.category,
       p.brand,
       f.snapshot_id,
       f.batch_id,
       f.captured_at,
       f.captured_date,
       f.price,
       f.currency,
       f.discount_percentage,
       f.price_after_discount,
       f.rating,
       f.stock,
       f.availability_status
FROM dwh.fact_price_snapshot f
JOIN dwh.dim_product p USING (product_key)
JOIN dwh.dim_source  s USING (source_key);
