-- 07_olist_checks.sql : sanity checks after the Olist clean load (read-only)

SELECT 'raw products (distinct)'      AS what, count(DISTINCT product_id) AS n FROM raw.olist_products
UNION ALL
SELECT 'dwh.dim_product (olist)',      count(*) FROM dwh.dim_product dp
    JOIN dwh.dim_source s USING (source_key) WHERE s.source_name = 'olist_csv'
UNION ALL
SELECT 'dwh.fact_price_snapshot (olist)', count(*) FROM dwh.fact_price_snapshot f
    JOIN dwh.dim_product dp USING (product_key)
    JOIN dwh.dim_source s USING (source_key) WHERE s.source_name = 'olist_csv'
UNION ALL
SELECT 'dwh.rejected_records (olist)', count(*) FROM dwh.rejected_records WHERE source_name = 'olist_csv';

-- Rejects by reason
SELECT reason, count(*) FROM dwh.rejected_records
WHERE source_name = 'olist_csv' GROUP BY reason ORDER BY 2 DESC;

-- Sample of the clean data
SELECT dp.category, f.captured_date, f.price, f.currency, f.rating
FROM dwh.fact_price_snapshot f
JOIN dwh.dim_product dp USING (product_key)
JOIN dwh.dim_source s USING (source_key)
WHERE s.source_name = 'olist_csv'
ORDER BY f.captured_date DESC LIMIT 10;
