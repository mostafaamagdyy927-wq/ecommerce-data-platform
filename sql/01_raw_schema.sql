CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.api_products (
    id          BIGSERIAL PRIMARY KEY,
    source_name TEXT        NOT NULL,
    batch_id    TEXT        NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload     JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_api_products_batch
    ON raw.api_products (batch_id);
