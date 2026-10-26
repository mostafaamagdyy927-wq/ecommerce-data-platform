\x on
SELECT
  count(*) AS total,
  count(DISTINCT payload->>'id') AS distinct_ids,
  count(*) FILTER (WHERE payload->>'brand' IS NULL) AS no_brand,
  count(*) FILTER (WHERE payload->>'title' IS NULL) AS no_title,
  count(*) FILTER (WHERE payload->>'category' IS NULL) AS no_category,
  count(*) FILTER (WHERE payload->>'price' IS NULL) AS no_price,
  count(*) FILTER (WHERE payload->>'sku' IS NULL) AS no_sku,
  min((payload->>'price')::numeric) AS min_price,
  max((payload->>'price')::numeric) AS max_price,
  min((payload->>'discountPercentage')::numeric) AS min_discount,
  max((payload->>'discountPercentage')::numeric) AS max_discount,
  min((payload->>'rating')::numeric) AS min_rating,
  max((payload->>'rating')::numeric) AS max_rating,
  min((payload->>'stock')::int) AS min_stock,
  max((payload->>'stock')::int) AS max_stock
FROM raw.api_products;
\x off
SELECT payload->>'category' AS category, count(*) AS n
FROM raw.api_products GROUP BY 1 ORDER BY 2 DESC;
SELECT payload->>'availabilityStatus' AS availability, count(*) AS n
FROM raw.api_products GROUP BY 1 ORDER BY 2 DESC;
