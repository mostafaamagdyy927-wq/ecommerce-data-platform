"""Transform raw API products into the warehouse (dwh) layer.

Reads one batch from raw.api_products, cleans and validates every record,
upserts dwh.dim_product, inserts dwh.fact_price_snapshot, and stores
invalid records in dwh.rejected_records with the reason.

Re-running the same batch is safe (idempotent): dimension rows are upserted,
snapshots are skipped if they already exist, and rejected rows for the batch
are replaced.
"""

import json
import logging
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from extract.api_client import SOURCE_NAME, get_engine

log = logging.getLogger("transform_products")


class RejectedRecord(Exception):
    """Raised when a raw record cannot be loaded into the warehouse."""


def _clean_text(value):
    """Trim and collapse inner whitespace; empty strings become None."""
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def _to_decimal(value, field, required=False):
    if value is None or value == "":
        if required:
            raise RejectedRecord(f"missing {field}")
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise RejectedRecord(f"invalid {field}: {value!r}")
    if not number.is_finite():
        raise RejectedRecord(f"invalid {field}: {value!r}")
    return number


def _to_int(value, field):
    number = _to_decimal(value, field)
    if number is None:
        return None
    if number != number.to_integral_value():
        raise RejectedRecord(f"invalid {field}: {value!r}")
    return int(number)


def _to_timestamp(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def category_label(category):
    """'mens-shirts' -> "Mens Shirts"."""
    if not category:
        return None
    return category.replace("-", " ").replace("_", " ").title()


def clean_product(payload):
    """Validate and standardize one raw product.

    Returns (dim, fact) dictionaries, or raises RejectedRecord.
    """
    if not isinstance(payload, dict):
        raise RejectedRecord("payload is not a JSON object")

    source_product_id = _clean_text(payload.get("id"))
    if source_product_id is None:
        raise RejectedRecord("missing id")

    title = _clean_text(payload.get("title"))
    if title is None:
        raise RejectedRecord("missing title")

    price = _to_decimal(payload.get("price"), "price", required=True)
    if price <= 0:
        raise RejectedRecord(f"price must be positive: {price}")

    discount = _to_decimal(payload.get("discountPercentage"), "discountPercentage")
    if discount is not None and not (0 <= discount <= 100):
        raise RejectedRecord(f"discountPercentage out of range: {discount}")

    rating = _to_decimal(payload.get("rating"), "rating")
    if rating is not None and not (0 <= rating <= 5):
        raise RejectedRecord(f"rating out of range: {rating}")

    stock = _to_int(payload.get("stock"), "stock")
    if stock is not None and stock < 0:
        raise RejectedRecord(f"stock must not be negative: {stock}")

    category = _clean_text(payload.get("category")) or "Unknown"
    dimensions = payload.get("dimensions") or {}
    meta = payload.get("meta") or {}
    tags = [t for t in (_clean_text(t) for t in payload.get("tags") or []) if t]

    price_after_discount = None
    if discount is not None:
        price_after_discount = (price * (1 - discount / 100)).quantize(Decimal("0.01"))

    dim = {
        "source_product_id": source_product_id,
        "sku": _clean_text(payload.get("sku")),
        "title": title,
        "category": category,
        "category_label": category_label(category),
        "brand": _clean_text(payload.get("brand")) or "Unknown",
        "description": _clean_text(payload.get("description")),
        "weight": _to_decimal(payload.get("weight"), "weight"),
        "width": _to_decimal(dimensions.get("width"), "width"),
        "height": _to_decimal(dimensions.get("height"), "height"),
        "depth": _to_decimal(dimensions.get("depth"), "depth"),
        "tags": tags,
        "thumbnail_url": _clean_text(payload.get("thumbnail")),
        "created_at_source": _to_timestamp(meta.get("createdAt")),
        "updated_at_source": _to_timestamp(meta.get("updatedAt")),
    }
    fact = {
        "price": price,
        "currency": "USD",
        "discount_percentage": discount,
        "price_after_discount": price_after_discount,
        "rating": rating,
        "stock": stock,
        "availability_status": _clean_text(payload.get("availabilityStatus")),
    }
    return dim, fact


UPSERT_DIM = text(
    """
    INSERT INTO dwh.dim_product (
        source_key, source_product_id, sku, title, category, category_label,
        brand, description, weight, width, height, depth, tags,
        thumbnail_url, created_at_source, updated_at_source
    ) VALUES (
        :source_key, :source_product_id, :sku, :title, :category,
        :category_label, :brand, :description, :weight, :width, :height,
        :depth, :tags, :thumbnail_url, :created_at_source, :updated_at_source
    )
    ON CONFLICT (source_key, source_product_id) DO UPDATE SET
        sku = EXCLUDED.sku,
        title = EXCLUDED.title,
        category = EXCLUDED.category,
        category_label = EXCLUDED.category_label,
        brand = EXCLUDED.brand,
        description = EXCLUDED.description,
        weight = EXCLUDED.weight,
        width = EXCLUDED.width,
        height = EXCLUDED.height,
        depth = EXCLUDED.depth,
        tags = EXCLUDED.tags,
        thumbnail_url = EXCLUDED.thumbnail_url,
        created_at_source = EXCLUDED.created_at_source,
        updated_at_source = EXCLUDED.updated_at_source
    RETURNING product_key
    """
)

INSERT_FACT = text(
    """
    INSERT INTO dwh.fact_price_snapshot (
        product_key, batch_id, captured_at, captured_date, price, currency,
        discount_percentage, price_after_discount, rating, stock,
        availability_status
    ) VALUES (
        :product_key, :batch_id, :captured_at, :captured_date, :price,
        :currency, :discount_percentage, :price_after_discount, :rating,
        :stock, :availability_status
    )
    ON CONFLICT (product_key, batch_id) DO NOTHING
    """
)


def latest_batch_id(conn):
    """The most recently ingested batch for this source, or None."""
    return conn.execute(
        text(
            """
            SELECT batch_id FROM raw.api_products
            WHERE source_name = :source
            GROUP BY batch_id
            ORDER BY max(ingested_at) DESC
            LIMIT 1
            """
        ),
        {"source": SOURCE_NAME},
    ).scalar()


def transform_batch(conn, batch_id):
    """Transform one raw batch inside the caller's transaction.

    Returns a dict with loaded / rejected counts.
    """
    source_key = conn.execute(
        text("SELECT source_key FROM dwh.dim_source WHERE source_name = :s"),
        {"s": SOURCE_NAME},
    ).scalar()
    if source_key is None:
        raise RuntimeError(
            f"{SOURCE_NAME} is missing from dwh.dim_source; apply sql/02_clean_schema.sql"
        )

    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (payload->>'id') id, payload, ingested_at
            FROM raw.api_products
            WHERE source_name = :s AND batch_id = :b
            ORDER BY payload->>'id', id
            """
        ),
        {"s": SOURCE_NAME, "b": batch_id},
    ).mappings().all()
    if not rows:
        raise RuntimeError(f"no raw rows found for batch {batch_id}")

    # Make re-runs idempotent: replace this batch's rejects.
    conn.execute(
        text(
            "DELETE FROM dwh.rejected_records WHERE source_name = :s AND batch_id = :b"
        ),
        {"s": SOURCE_NAME, "b": batch_id},
    )

    loaded = 0
    rejected = 0
    for row in rows:
        try:
            dim, fact = clean_product(row["payload"])
        except RejectedRecord as exc:
            rejected += 1
            conn.execute(
                text(
                    """
                    INSERT INTO dwh.rejected_records
                        (source_name, batch_id, raw_id, reason, payload)
                    VALUES (:s, :b, :raw_id, :reason, CAST(:payload AS JSONB))
                    """
                ),
                {
                    "s": SOURCE_NAME,
                    "b": batch_id,
                    "raw_id": row["id"],
                    "reason": str(exc),
                    "payload": json.dumps(row["payload"]),
                },
            )
            continue

        product_key = conn.execute(
            UPSERT_DIM, {**dim, "source_key": source_key}
        ).scalar_one()
        captured_at = row["ingested_at"]
        conn.execute(
            INSERT_FACT,
            {
                **fact,
                "product_key": product_key,
                "batch_id": batch_id,
                "captured_at": captured_at,
                "captured_date": captured_at.date(),
            },
        )
        loaded += 1

    return {"batch_id": batch_id, "loaded": loaded, "rejected": rejected}


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    engine = get_engine()
    try:
        with engine.begin() as conn:
            batch_id = os.getenv("PIPELINE_BATCH_ID") or latest_batch_id(conn)
            if batch_id is None:
                raise RuntimeError("no raw batches found; run the extract step first")
            log.info("Transforming batch %s", batch_id)
            result = transform_batch(conn, batch_id)
        log.info(
            "Batch %s done: %s loaded, %s rejected",
            result["batch_id"],
            result["loaded"],
            result["rejected"],
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
