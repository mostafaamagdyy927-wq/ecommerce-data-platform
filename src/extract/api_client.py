"""Extract products from a public test API and store them untouched
in the raw layer (raw.api_products)."""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

SOURCE_NAME = "dummyjson_api"
API_URL = "https://dummyjson.com/products"
PAGE_SIZE = 100
MAX_RETRIES = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("api_client")


def get_engine():
    url = URL.create(
        "postgresql+psycopg2",
        username=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host="localhost",
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB"),
    )
    return create_engine(url)


def fetch_page(skip):
    """Fetch one page from the API, retrying on network errors."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                API_URL,
                params={"limit": PAGE_SIZE, "skip": skip},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            log.warning("Attempt %s/%s failed: %s", attempt, MAX_RETRIES, exc)
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2 * attempt)


def fetch_all_products():
    """Walk through all pages and return the full product list."""
    products = []
    skip = 0
    while True:
        data = fetch_page(skip)
        page = data.get("products", [])
        products.extend(page)
        total = data.get("total", len(products))
        skip += PAGE_SIZE
        if not page or len(products) >= total:
            break
    return products


def save_raw(products, batch_id):
    """Insert every product as-is (JSON) into raw.api_products."""
    rows = [
        {
            "source_name": SOURCE_NAME,
            "batch_id": batch_id,
            "payload": json.dumps(p),
        }
        for p in products
    ]
    sql = text(
        """
        INSERT INTO raw.api_products (source_name, batch_id, payload)
        VALUES (:source_name, :batch_id, CAST(:payload AS JSONB))
        """
    )
    with get_engine().begin() as conn:
        conn.execute(sql, rows)
    return len(rows)


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    batch_id = f"{stamp}-{uuid.uuid4().hex[:6]}"
    log.info("Starting batch %s", batch_id)

    products = fetch_all_products()
    log.info("Fetched %s products", len(products))
    if not products:
        raise RuntimeError("API returned no products")

    saved = save_raw(products, batch_id)
    log.info("Saved %s rows into raw.api_products", saved)


if __name__ == "__main__":
    main()