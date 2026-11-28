"""Load the scraped books JSON into the raw layer (raw.scraped_products).

Idempotent: the batch id comes from the file content, so loading the same
books_raw.json twice stores the batch once. A new scrape (new file content)
becomes a new batch.
"""

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

SOURCE_NAME = "books_to_scrape"
INPUT_FILE = ROOT / "data" / "raw" / "books_raw.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("books_loader")


def get_engine():
    required_vars = [
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
    ]

    missing = [key for key in required_vars if not os.getenv(key)]
    if missing:
        raise RuntimeError(
            f"Missing environment variables: {', '.join(missing)}"
        )

    url = URL.create(
        "postgresql+psycopg2",
        username=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB"),
    )
    return create_engine(url)


def load_books():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Input file not found: {INPUT_FILE}"
        )

    with INPUT_FILE.open("r", encoding="utf-8") as file:
        books = json.load(file)

    if not isinstance(books, list):
        raise ValueError("Expected a JSON list of books")

    if not books:
        raise ValueError("Input file contains no books")

    for index, book in enumerate(books):
        if not isinstance(book, dict):
            raise ValueError(f"Book at index {index} is not an object")

        for field in ("title", "price", "product_url"):
            if not book.get(field):
                raise ValueError(
                    f"Book at index {index} is missing '{field}'"
                )

    return books


def make_batch_id(books):
    """PIPELINE_BATCH_ID (orchestrator) wins, otherwise a hash of the content.

    Same file -> same batch id, so re-running the loader (or an Airflow retry)
    never stores the same books twice. Mirrors load.olist_loader.
    """
    provided = os.getenv("PIPELINE_BATCH_ID")
    if provided:
        return provided
    canonical = sorted(books, key=lambda book: str(book.get("product_url") or ""))
    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "books_" + hashlib.sha256(payload).hexdigest()[:12]


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


def save_raw(books, batch_id):
    insert_sql = text(
        """
        INSERT INTO raw.scraped_products
            (source_name, batch_id, payload)
        VALUES
            (:source_name, :batch_id, CAST(:payload AS JSONB))
        """
    )

    rows = [
        {
            "source_name": SOURCE_NAME,
            "batch_id": batch_id,
            "payload": json.dumps(book, ensure_ascii=False),
        }
        for book in books
    ]

    engine = get_engine()
    try:
        with engine.begin() as connection:
            connection.execute(insert_sql, rows)
    finally:
        engine.dispose()

    return len(rows)


def main():
    books = load_books()
    batch_id = make_batch_id(books)

    log.info("Source: %s", SOURCE_NAME)
    log.info("Batch ID: %s", batch_id)
    log.info("Books loaded from JSON: %s", len(books))

    engine = get_engine()
    try:
        if batch_already_loaded(engine, batch_id):
            log.info("Batch %s already in raw.scraped_products, nothing to do", batch_id)
            return
    finally:
        engine.dispose()

    saved = save_raw(books, batch_id)

    log.info("Rows inserted: %s", saved)
    log.info("Target table: raw.scraped_products")


if __name__ == "__main__":
    main()

