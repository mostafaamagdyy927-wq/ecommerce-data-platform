CREATE TABLE IF NOT EXISTS raw.scraped_products (
    id          BIGSERIAL PRIMARY KEY,
    source_name TEXT        NOT NULL,
    batch_id    TEXT        NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload     JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_scraped_products_batch
    ON raw.scraped_products (source_name, batch_id);