CREATE SCHEMA IF NOT EXISTS dwh;

CREATE TABLE IF NOT EXISTS dwh.dim_source (
    source_key  SMALLSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL UNIQUE,
    data_origin TEXT NOT NULL
        CHECK (data_origin IN ('fake_api', 'real_dataset', 'generated', 'scraped')),
    description TEXT
);

INSERT INTO dwh.dim_source (source_name, data_origin, description)
VALUES ('dummyjson_api', 'fake_api',
        'DummyJSON public fake API (test data, not real market prices)')
ON CONFLICT (source_name) DO NOTHING;

CREATE TABLE IF NOT EXISTS dwh.dim_product (
    product_key       BIGSERIAL PRIMARY KEY,
    source_key        SMALLINT NOT NULL REFERENCES dwh.dim_source (source_key),
    source_product_id TEXT NOT NULL,
    sku               TEXT,
    title             TEXT,
    category          TEXT NOT NULL DEFAULT 'Unknown',
    category_label    TEXT,
    brand             TEXT NOT NULL DEFAULT 'Unknown',
    description       TEXT,
    weight            NUMERIC(10, 2),
    width             NUMERIC(10, 2),
    height            NUMERIC(10, 2),
    depth             NUMERIC(10, 2),
    tags              TEXT[],
    thumbnail_url     TEXT,
    created_at_source TIMESTAMPTZ,
    updated_at_source TIMESTAMPTZ,
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_key, source_product_id)
);

CREATE TABLE IF NOT EXISTS dwh.fact_price_snapshot (
    snapshot_id          BIGSERIAL PRIMARY KEY,
    product_key          BIGINT NOT NULL REFERENCES dwh.dim_product (product_key),
    batch_id             TEXT NOT NULL,
    captured_at          TIMESTAMPTZ NOT NULL,
    captured_date        DATE NOT NULL,
    price                NUMERIC(12, 2) NOT NULL CHECK (price > 0),
    currency             CHAR(3) NOT NULL DEFAULT 'USD',
    discount_percentage  NUMERIC(5, 2) CHECK (discount_percentage BETWEEN 0 AND 100),
    price_after_discount NUMERIC(12, 2),
    rating               NUMERIC(3, 2) CHECK (rating BETWEEN 0 AND 5),
    stock                INTEGER CHECK (stock >= 0),
    availability_status  TEXT,
    UNIQUE (product_key, batch_id)
);

CREATE INDEX IF NOT EXISTS idx_fps_product_time
    ON dwh.fact_price_snapshot (product_key, captured_at);
CREATE INDEX IF NOT EXISTS idx_fps_date
    ON dwh.fact_price_snapshot (captured_date);

CREATE TABLE IF NOT EXISTS dwh.rejected_records (
    id          BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    batch_id    TEXT NOT NULL,
    raw_id      BIGINT,
    reason      TEXT NOT NULL,
    payload     JSONB,
    rejected_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
