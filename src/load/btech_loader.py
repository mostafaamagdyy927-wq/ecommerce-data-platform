"""Load the B.TECH products CSV into the raw layer (raw.scraped_products).

The CSV is already extracted (scraped earlier), so there is no extract step:
this loader reads the file and stores each row as JSONB, untouched.

Idempotent: the batch id comes from the file content, so loading the same CSV
twice stores the batch once. A new CSV (new content) becomes a new batch.

Only rows that are exactly identical are dropped here. Product level
de-duplication (same product, different offering_id) is the transform's job.
"""

import csv
import hashlib
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

SOURCE_NAME = "btech"
INPUT_FILE = ROOT / "data" / "raw" / "btech_products_all_categories.csv"
REQUIRED_FIELDS = ("title", "current_price", "url")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("btech_loader")


def get_engine():
    required_vars = ["POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"]
    missing = [key for key in required_vars if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")

    url = URL.create(
        "postgresql+psycopg2",
        username=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB"),
    )
    return create_engine(url)


def load_rows():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    # utf-8-sig strips the BOM the file starts with
    with INPUT_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    if not rows:
        raise ValueError("Input file contains no rows")

    for index, row in enumerate(rows):
        for field in REQUIRED_FIELDS:
            if not (row.get(field) or "").strip():
                raise ValueError(f"Row {index} is missing '{field}'")

    return drop_identical_rows(rows)


def drop_identical_rows(rows):
    seen = set()
    unique = []
    for row in rows:
        key = json.dumps(row, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def make_batch_id(rows):
    """PIPELINE_BATCH_ID (orchestrator) wins, otherwise a hash of the content."""
    provided = os.getenv("PIPELINE_BATCH_ID")
    if provided:
        return provided
    canonical = sorted(rows, key=lambda row: str(row.get("url") or ""))
    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "btech_" + hashlib.sha256(payload).hexdigest()[:12]


def batch_already_loaded(engine, batch_id):
    with engine.connect() as connection:
        count = connection.execute(
            text(
                """
                SELECT count(*) FROM raw.scraped_products
                WHERE source_name = :source_name AND batch_id = :batch_id
                """
            ),
            {"source_name": SOURCE_NAME, "batch_id": batch_id},
        ).scalar_one()
    return count > 0


def save_raw(rows, batch_id):
    insert_sql = text(
        """
        INSERT INTO raw.scraped_products
            (source_name, batch_id, payload)
        VALUES
            (:source_name, :batch_id, CAST(:payload AS JSONB))
        """
    )
    records = [
        {
            "source_name": SOURCE_NAME,
            "batch_id": batch_id,
            "payload": json.dumps(row, ensure_ascii=False),
        }
        for row in rows
    ]

    engine = get_engine()
    try:
        with engine.begin() as connection:
            connection.execute(insert_sql, records)
    finally:
        engine.dispose()
    return len(records)


def main():
    rows = load_rows()
    batch_id = make_batch_id(rows)

    log.info("Source: %s", SOURCE_NAME)
    log.info("Batch ID: %s", batch_id)
    log.info("Rows after dropping identical rows: %s", len(rows))

    engine = get_engine()
    try:
        if batch_already_loaded(engine, batch_id):
            log.info("Batch %s already in raw.scraped_products, nothing to do", batch_id)
            return
    finally:
        engine.dispose()

    saved = save_raw(rows, batch_id)
    log.info("Rows inserted: %s", saved)
    log.info("Target table: raw.scraped_products")


if __name__ == "__main__":
    main()
