"""Integration test against a real PostgreSQL.

Skipped unless TEST_DATABASE_URL is set, e.g.
    TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/testdb pytest
The target database is wiped (raw and dwh schemas are dropped), so use a
throwaway database.
"""

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from transform.transform_products import latest_batch_id, transform_batch

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
DB_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture()
def engine():
    engine = create_engine(DB_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS raw CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS dwh CASCADE"))
        for name in ("01_raw_schema.sql", "02_clean_schema.sql"):
            conn.exec_driver_sql((SQL_DIR / name).read_text())
    yield engine
    engine.dispose()


def insert_raw(conn, batch_id, products):
    for product in products:
        conn.execute(
            text(
                "INSERT INTO raw.api_products (source_name, batch_id, payload) "
                "VALUES ('dummyjson_api', :b, CAST(:p AS JSONB))"
            ),
            {"b": batch_id, "p": json.dumps(product)},
        )


PRODUCTS = [
    {"id": 1, "title": "Good", "price": 10, "category": "beauty", "stock": 3},
    {"id": 2, "title": "Bad price", "price": -5},
    {"id": 3, "title": "Also good", "price": 20, "brand": "Acme"},
]


def counts(conn):
    return {
        table: conn.execute(text(f"SELECT count(*) FROM dwh.{table}")).scalar()
        for table in ("dim_product", "fact_price_snapshot", "rejected_records")
    }


def test_transform_loads_and_rejects(engine):
    with engine.begin() as conn:
        insert_raw(conn, "b1", PRODUCTS)
        result = transform_batch(conn, "b1")
        assert result["loaded"] == 2 and result["rejected"] == 1
        assert counts(conn) == {
            "dim_product": 2,
            "fact_price_snapshot": 2,
            "rejected_records": 1,
        }
        reason = conn.execute(text("SELECT reason FROM dwh.rejected_records")).scalar()
        assert "price must be positive" in reason


def test_rerun_is_idempotent(engine):
    with engine.begin() as conn:
        insert_raw(conn, "b1", PRODUCTS)
        transform_batch(conn, "b1")
        first = counts(conn)
        transform_batch(conn, "b1")
        assert counts(conn) == first


def test_new_batch_adds_snapshot_and_updates_dimension(engine):
    with engine.begin() as conn:
        insert_raw(conn, "b1", PRODUCTS)
        transform_batch(conn, "b1")
        changed = [dict(PRODUCTS[0], price=12, category="skin-care")]
        insert_raw(conn, "b2", changed)
        transform_batch(conn, "b2")

        assert counts(conn)["dim_product"] == 2
        assert counts(conn)["fact_price_snapshot"] == 3
        prices = conn.execute(
            text(
                "SELECT f.price FROM dwh.fact_price_snapshot f "
                "JOIN dwh.dim_product d USING (product_key) "
                "WHERE d.source_product_id = '1' ORDER BY f.captured_at, f.snapshot_id"
            )
        ).scalars().all()
        assert [int(p) for p in prices] == [10, 12]
        category = conn.execute(
            text("SELECT category FROM dwh.dim_product WHERE source_product_id = '1'")
        ).scalar()
        assert category == "skin-care"


def test_duplicate_raw_rows_in_one_batch_are_collapsed(engine):
    with engine.begin() as conn:
        # Simulates a database where the unique index is not present.
        conn.execute(text("DROP INDEX raw.uq_raw_api_products_batch_item"))
        insert_raw(conn, "b1", [PRODUCTS[0], PRODUCTS[0]])
        result = transform_batch(conn, "b1")
        assert result["loaded"] == 1
        assert latest_batch_id(conn) == "b1"
