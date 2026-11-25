"""Load the 9 Olist CSV files untouched into the raw layer (raw.olist_*).

Every value is stored as TEXT (empty string becomes NULL). Re-running the same
files is safe: the batch id is derived from the file contents and rows are
inserted with ON CONFLICT (source_name, batch_id, row_num) DO NOTHING.

Usage:
    python -m load.olist_loader                      # from the repo root, with PYTHONPATH=src
    python src/load/olist_loader.py --data-dir data/sample/olist
    python src/load/olist_loader.py --skip-geolocation
"""

import argparse
import csv
import hashlib
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from psycopg2.extras import execute_values
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[2]

SOURCE_NAME = "olist_csv"
DEFAULT_DATA_DIR = ROOT / "data" / "olist"
CHUNK_SIZE = 5000
REQUIRED_ENV = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")

# file name -> (target table, expected columns). Column names match the CSV
# headers exactly (including Olist's own typo "lenght").
FILES = {
    "olist_orders_dataset.csv": (
        "raw.olist_orders",
        [
            "order_id", "customer_id", "order_status",
            "order_purchase_timestamp", "order_approved_at",
            "order_delivered_carrier_date", "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
    ),
    "olist_order_items_dataset.csv": (
        "raw.olist_order_items",
        [
            "order_id", "order_item_id", "product_id", "seller_id",
            "shipping_limit_date", "price", "freight_value",
        ],
    ),
    "olist_order_payments_dataset.csv": (
        "raw.olist_order_payments",
        [
            "order_id", "payment_sequential", "payment_type",
            "payment_installments", "payment_value",
        ],
    ),
    "olist_order_reviews_dataset.csv": (
        "raw.olist_order_reviews",
        [
            "review_id", "order_id", "review_score", "review_comment_title",
            "review_comment_message", "review_creation_date",
            "review_answer_timestamp",
        ],
    ),
    "olist_customers_dataset.csv": (
        "raw.olist_customers",
        [
            "customer_id", "customer_unique_id", "customer_zip_code_prefix",
            "customer_city", "customer_state",
        ],
    ),
    "olist_sellers_dataset.csv": (
        "raw.olist_sellers",
        ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"],
    ),
    "olist_products_dataset.csv": (
        "raw.olist_products",
        [
            "product_id", "product_category_name", "product_name_lenght",
            "product_description_lenght", "product_photos_qty",
            "product_weight_g", "product_length_cm", "product_height_cm",
            "product_width_cm",
        ],
    ),
    "olist_geolocation_dataset.csv": (
        "raw.olist_geolocation",
        [
            "geolocation_zip_code_prefix", "geolocation_lat",
            "geolocation_lng", "geolocation_city", "geolocation_state",
        ],
    ),
    "product_category_name_translation.csv": (
        "raw.olist_category_translation",
        ["product_category_name", "product_category_name_english"],
    ),
}

GEOLOCATION_FILE = "olist_geolocation_dataset.csv"

log = logging.getLogger("olist_loader")


def get_engine():
    """Same convention as api_client.get_engine (env vars from .env)."""
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


def selected_files(skip_geolocation=False):
    return {
        name: spec
        for name, spec in FILES.items()
        if not (skip_geolocation and name == GEOLOCATION_FILE)
    }


def check_files_exist(folder, files):
    missing = [name for name in files if not (folder / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing Olist files in {folder}: {', '.join(sorted(missing))}"
        )


def compute_batch_id(folder, files):
    """olist_<first 12 hex of sha256> over the files, sorted by name.

    The file name is hashed too, so renaming/swapping files changes the id.
    Same files -> same batch id -> re-runs never duplicate rows.
    """
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8"))
        with (folder / name).open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return "olist_" + digest.hexdigest()[:12]


def make_batch_id(folder, files, explicit=None):
    """--batch-id wins, then PIPELINE_BATCH_ID (orchestrator), then file hash."""
    if explicit:
        return explicit
    provided = os.getenv("PIPELINE_BATCH_ID")
    if provided:
        return provided
    return compute_batch_id(folder, files)


def _normalize(name):
    return name.strip().strip('"').strip("'").lstrip("\ufeff").strip().lower()


def resolve_header(file_name, header, expected):
    """Return, for each expected column, its index in the file header.

    Fails loudly with a clear message when columns are missing or unknown.
    Column order may differ from `expected` (mapped by name). Tolerance for
    the geolocation file only: names without the `geolocation_` prefix
    (zip_code_prefix, lat, lng, city, state) are accepted too.
    """
    found = [_normalize(col) for col in header]

    if file_name == GEOLOCATION_FILE:
        prefix = "geolocation_"
        found = [
            col if col.startswith(prefix) else prefix + col for col in found
        ]

    if len(set(found)) != len(found):
        raise ValueError(f"{file_name}: duplicate columns in header {header}")

    missing = [col for col in expected if col not in found]
    extra = [col for col in found if col not in expected]
    if missing or extra:
        raise ValueError(
            f"{file_name}: unexpected header. "
            f"missing={missing} unexpected={extra} got={header}"
        )
    return [found.index(col) for col in expected]


def read_rows(path, expected):
    """Yield (row_num, values) with values ordered like `expected`.

    row_num starts at 1 for the first data row. Empty strings become None.
    Uses csv.reader because comment fields can span several lines.
    """
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"{path.name}: file is empty") from None

        order = resolve_header(path.name, header, expected)
        width = len(header)
        row_num = 0
        for row in reader:
            if not row:  # blank line
                continue
            row_num += 1
            if len(row) != width:
                raise ValueError(
                    f"{path.name}: data row {row_num} has {len(row)} fields, "
                    f"expected {width}"
                )
            yield row_num, [(row[i] if row[i] != "" else None) for i in order]
        if row_num == 0:
            raise ValueError(f"{path.name}: file has a header but no rows")


def _chunks(rows, size):
    chunk = []
    for item in rows:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def load_table(conn, table, cols, rows, batch_id, chunk_size=CHUNK_SIZE):
    """Insert rows into `table` with one multi-row INSERT per chunk.

    `conn` is a DBAPI (psycopg2) connection; the caller commits.
    Returns (rows_read, rows_inserted). Rows that already exist for this
    (source_name, batch_id, row_num) are skipped silently.
    """
    sql = (
        f"INSERT INTO {table} (source_name, batch_id, row_num, "
        f"{', '.join(cols)}) VALUES %s "
        "ON CONFLICT (source_name, batch_id, row_num) DO NOTHING "
        "RETURNING 1"
    )
    read = inserted = 0
    with conn.cursor() as cur:
        for chunk in _chunks(rows, chunk_size):
            values = [
                (SOURCE_NAME, batch_id, row_num, *vals)
                for row_num, vals in chunk
            ]
            result = execute_values(
                cur, sql, values, page_size=len(values), fetch=True
            )
            read += len(values)
            inserted += len(result)
    return read, inserted


def load_olist(engine, folder, batch_id=None, skip_geolocation=False):
    """Validate every file first, then load each file in its own transaction.

    Returns {table: (rows_read, rows_inserted)} and the batch id used.
    """
    folder = Path(folder)
    files = selected_files(skip_geolocation)
    check_files_exist(folder, files)

    # Fail before touching the database if any header is wrong.
    for name, (_, cols) in files.items():
        with (folder / name).open("r", encoding="utf-8-sig", newline="") as fh:
            header = next(csv.reader(fh), None)
        if header is None:
            raise ValueError(f"{name}: file is empty")
        resolve_header(name, header, cols)

    batch_id = make_batch_id(folder, files, batch_id)
    log.info("Source: %s", SOURCE_NAME)
    log.info("Batch ID: %s", batch_id)

    summary = {}
    for name, (table, cols) in files.items():
        raw_conn = engine.raw_connection()
        try:
            read, inserted = load_table(
                raw_conn, table, cols,
                read_rows(folder / name, cols), batch_id,
            )
            raw_conn.commit()
        except Exception:
            raw_conn.rollback()
            raise
        finally:
            raw_conn.close()
        summary[table] = (read, inserted)
        log.info(
            "%s: read=%s inserted=%s skipped=%s",
            table, read, inserted, read - inserted,
        )
    return summary, batch_id


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Load Olist CSVs into raw.olist_*")
    parser.add_argument(
        "--data-dir",
        default=os.getenv("OLIST_DATA_DIR") or str(DEFAULT_DATA_DIR),
        help="folder with the 9 CSV files (default: data/olist)",
    )
    parser.add_argument("--batch-id", help="override the file-hash batch id")
    parser.add_argument(
        "--skip-geolocation",
        action="store_true",
        help="do not load olist_geolocation_dataset.csv (~1M rows)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    args = parse_args(argv)
    folder = Path(args.data_dir)
    if not folder.is_absolute():
        folder = ROOT / folder

    engine = get_engine()
    try:
        summary, batch_id = load_olist(
            engine, folder, args.batch_id, args.skip_geolocation
        )
    finally:
        engine.dispose()

    total_read = sum(r for r, _ in summary.values())
    total_new = sum(i for _, i in summary.values())
    log.info(
        "Done batch %s: %s tables, %s rows read, %s inserted",
        batch_id, len(summary), total_read, total_new,
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        log.error("%s", exc)
        sys.exit(1)
