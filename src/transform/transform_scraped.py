"""Transform raw scraped products (books.toscrape.com) into the dwh layer.

Reads one batch from raw.scraped_products, cleans every record, upserts
dwh.dim_product, inserts dwh.fact_price_snapshot, and stores invalid records
in dwh.rejected_records. Re-running a batch is safe (idempotent).
"""

import json
import logging
import os
import re

from sqlalchemy import text

from extract.api_client import get_engine
from transform.transform_products import (
    INSERT_FACT,
    UPSERT_DIM,
    RejectedRecord,
    _clean_text,
    _to_decimal,
)

SOURCE_NAME = "books_to_scrape"
log = logging.getLogger("transform_scraped")

CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR"}
RATING_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def parse_price(value):
    """'£51.77' -> (Decimal('51.77'), 'GBP'). Raises RejectedRecord if bad."""
    raw = _clean_text(value)
    if raw is None:
        raise RejectedRecord("missing price")
    currency = "GBP"
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in raw:
            currency = code
    number = re.sub(r"[^0-9.\-]", "", raw)
    price = _to_decimal(number, "price", required=True)
    if price <= 0:
        raise RejectedRecord(f"price must be positive: {price}")
    return price, currency


def parse_rating(value):
    """'Three' or 3 -> Decimal 3; unknown -> None."""
    if value is None or value == "":
        return None
    word = str(value).strip().lower()
    if word in RATING_WORDS:
        return _to_decimal(RATING_WORDS[word], "rating")
    rating = _to_decimal(word, "rating")
    if rating is not None and not (0 <= rating <= 5):
        raise RejectedRecord(f"rating out of range: {rating}")
    return rating


def parse_stock(value):
    """'In stock (22 available)' -> 22; no number -> None."""
    match = re.search(r"(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def clean_book(payload):
    """Validate and standardize one raw scraped book. Returns (dim, fact)."""
    if not isinstance(payload, dict):
        raise RejectedRecord("payload is not a JSON object")

    url = _clean_text(payload.get("product_url"))
    if url is None:
        raise RejectedRecord("missing product_url")
    title = _clean_text(payload.get("title"))
    if title is None:
        raise RejectedRecord("missing title")

    price, currency = parse_price(payload.get("price"))
    availability = _clean_text(
        payload.get("availability") or payload.get("stock_text")
    )
    category = _clean_text(payload.get("category")) or "Unknown"

    dim = {
        "source_product_id": url,
        "sku": _clean_text(payload.get("upc")),
        "title": title,
        "category": category,
        "category_label": category,
        "brand": "Unknown",
        "description": _clean_text(payload.get("description")),
        "weight": None,
        "width": None,
        "height": None,
        "depth": None,
        "tags": [],
        "thumbnail_url": _clean_text(
            payload.get("image_url") or payload.get("thumbnail")
        ),
        "created_at_source": None,
        "updated_at_source": None,
    }
    fact = {
        "price": price,
        "currency": currency,
        "discount_percentage": None,
        "price_after_discount": None,
        "rating": parse_rating(payload.get("rating")),
        "stock": parse_stock(availability),
        "availability_status": availability,
    }
    return dim, fact


def latest_batch_id(conn):
    return conn.execute(
        text(
            """
            SELECT batch_id FROM raw.scraped_products
            WHERE source_name = :s
            GROUP BY batch_id
            ORDER BY max(ingested_at) DESC
            LIMIT 1
            """
        ),
        {"s": SOURCE_NAME},
    ).scalar()


def transform_batch(conn, batch_id):
    source_key = conn.execute(
        text("SELECT source_key FROM dwh.dim_source WHERE source_name = :s"),
        {"s": SOURCE_NAME},
    ).scalar()
    if source_key is None:
        raise RuntimeError(
            f"{SOURCE_NAME} is missing from dwh.dim_source; apply sql/08_clean_sources.sql"
        )

    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (payload->>'product_url') id, payload, ingested_at
            FROM raw.scraped_products
            WHERE source_name = :s AND batch_id = :b
            ORDER BY payload->>'product_url', id
            """
        ),
        {"s": SOURCE_NAME, "b": batch_id},
    ).mappings().all()
    if not rows:
        raise RuntimeError(f"no raw rows found for batch {batch_id}")

    conn.execute(
        text("DELETE FROM dwh.rejected_records WHERE source_name = :s AND batch_id = :b"),
        {"s": SOURCE_NAME, "b": batch_id},
    )

    loaded = rejected = 0
    for row in rows:
        try:
            dim, fact = clean_book(row["payload"])
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    engine = get_engine()
    try:
        with engine.begin() as conn:
            batch_id = os.getenv("SCRAPED_BATCH_ID") or latest_batch_id(conn)
            if batch_id is None:
                raise RuntimeError("no scraped batches found; run books_loader first")
            log.info("Transforming scraped batch %s", batch_id)
            result = transform_batch(conn, batch_id)
        log.info("Batch %s done: %s loaded, %s rejected",
                 result["batch_id"], result["loaded"], result["rejected"])
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
