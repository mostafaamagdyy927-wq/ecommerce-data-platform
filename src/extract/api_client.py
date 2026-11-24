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

SOURCE_NAME = "dummyjson_api"
API_URL = "https://dummyjson.com/products"
PAGE_SIZE = 100
MAX_RETRIES = 3
REQUEST_TIMEOUT = 15
USER_AGENT = "ecommerce-data-platform/0.1 (DEPI graduation project)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
REQUIRED_ENV = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")

log = logging.getLogger("api_client")


def get_engine():
    """Build a SQLAlchemy engine from environment variables.

    POSTGRES_HOST defaults to localhost (override it to `postgres` inside
    Docker/Airflow, or to your Azure server name). POSTGRES_SSLMODE is
    optional (use `require` for managed cloud databases such as Azure).
    """
    load_dotenv(ROOT / ".env")

    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing environment variables: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill them in."
        )

    query = {}
    sslmode = os.getenv("POSTGRES_SSLMODE")
    if sslmode:
        query["sslmode"] = sslmode

    url = URL.create(
        "postgresql+psycopg2",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.environ["POSTGRES_DB"],
        query=query,
    )
    return create_engine(url)


def _is_retryable(exc):
    """Retry network errors and transient HTTP statuses, not client errors."""
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        return response is not None and response.status_code in RETRYABLE_STATUS
    return True  # timeouts, connection errors, etc.


def _retry_delay(exc, attempt):
    """Honor a numeric Retry-After header, otherwise back off linearly."""
    response = getattr(exc, "response", None)
    if response is not None:
        retry_after = response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(int(retry_after), 60)
    return 2 * attempt


def fetch_page(skip):
    """Fetch one page from the API, retrying only on transient errors."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                API_URL,
                params={"limit": PAGE_SIZE, "skip": skip},
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES or not _is_retryable(exc):
                raise
            log.warning("Attempt %s/%s failed: %s", attempt, MAX_RETRIES, exc)
            time.sleep(_retry_delay(exc, attempt))


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


def make_batch_id():
    """Use PIPELINE_BATCH_ID when the orchestrator provides one (e.g. the
    Airflow run id) so a retried run reuses the same id and stays
    idempotent; otherwise generate a unique id."""
    provided = os.getenv("PIPELINE_BATCH_ID")
    if provided:
        return provided
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def save_raw(products, batch_id):
    """Insert every product as-is (JSON) into raw.api_products.

    Re-running the same batch_id is safe: rows already stored for that
    batch are skipped (unique index on source, batch and product id).
    """
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
        ON CONFLICT DO NOTHING
        """
    )
    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(sql, rows)
    finally:
        engine.dispose()
    return len(rows)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    batch_id = make_batch_id()
    log.info("Starting batch %s", batch_id)

    products = fetch_all_products()
    log.info("Fetched %s products", len(products))
    if not products:
        raise RuntimeError("API returned no products")

    processed = save_raw(products, batch_id)
    log.info("Processed %s rows into raw.api_products", processed)


if __name__ == "__main__":
    main()
