"""Unit tests for load.olist_loader (no database needed).

The last test is an integration test, skipped unless TEST_DATABASE_URL is set:
    TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/testdb pytest
It DROPS the raw schema in that database, so use a throwaway database.
"""

import csv
import os
from pathlib import Path

import pytest

from load import olist_loader as ol

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
DB_URL = os.getenv("TEST_DATABASE_URL")


def write_csv(path, header, rows, bom=False):
    with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def make_folder(folder, rows_per_file=3, only=None):
    """Create all 9 fake CSVs with `rows_per_file` rows each."""
    for name, (_, cols) in ol.FILES.items():
        if only and name not in only:
            continue
        rows = [[f"{col}_{i}" for col in cols] for i in range(rows_per_file)]
        write_csv(folder / name, cols, rows)
    return folder


def test_read_rows_maps_empty_to_none_and_numbers_rows(tmp_path):
    cols = ["a", "b"]
    path = tmp_path / "x.csv"
    write_csv(path, cols, [["1", ""], ["2", "z"]])
    assert list(ol.read_rows(path, cols)) == [(1, ["1", None]), (2, ["2", "z"])]


def test_read_rows_handles_bom_and_multiline_fields(tmp_path):
    name = "product_category_name_translation.csv"
    cols = ol.FILES[name][1]
    path = tmp_path / name
    write_csv(path, cols, [["beleza", "line one\nline two"]], bom=True)
    rows = list(ol.read_rows(path, cols))
    assert rows == [(1, ["beleza", "line one\nline two"])]


def test_header_in_different_order_is_mapped_by_name(tmp_path):
    path = tmp_path / "olist_sellers_dataset.csv"
    cols = ol.FILES[path.name][1]
    write_csv(path, list(reversed(cols)), [["SP", "sao paulo", "01000", "s1"]])
    assert list(ol.read_rows(path, cols)) == [
        (1, ["s1", "01000", "sao paulo", "SP"])
    ]


def test_wrong_header_fails_loudly(tmp_path):
    path = tmp_path / "olist_sellers_dataset.csv"
    write_csv(path, ["seller_id", "zip", "city", "state"], [["1", "2", "3", "4"]])
    with pytest.raises(ValueError, match="unexpected header"):
        list(ol.read_rows(path, ol.FILES[path.name][1]))


def test_geolocation_header_without_prefix_is_tolerated(tmp_path):
    path = tmp_path / ol.GEOLOCATION_FILE
    write_csv(
        path,
        ["zip_code_prefix", "lat", "lng", "city", "state"],
        [["01037", "-23.5", "-46.6", "sao paulo", "SP"]],
    )
    rows = list(ol.read_rows(path, ol.FILES[ol.GEOLOCATION_FILE][1]))
    assert rows == [(1, ["01037", "-23.5", "-46.6", "sao paulo", "SP"])]


def test_prefix_tolerance_does_not_apply_to_other_files(tmp_path):
    path = tmp_path / "olist_sellers_dataset.csv"
    write_csv(path, ["id", "zip", "city", "state"], [["1", "2", "3", "4"]])
    with pytest.raises(ValueError):
        list(ol.read_rows(path, ol.FILES[path.name][1]))


def test_row_with_wrong_field_count_fails(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("a,b\n1,2\n3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="row 2"):
        list(ol.read_rows(path, ["a", "b"]))


def test_empty_file_and_header_only_file_fail(tmp_path):
    empty = tmp_path / "e.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        list(ol.read_rows(empty, ["a"]))
    header_only = tmp_path / "h.csv"
    header_only.write_text("a\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no rows"):
        list(ol.read_rows(header_only, ["a"]))


def test_missing_file_is_reported(tmp_path):
    make_folder(tmp_path)
    (tmp_path / "olist_orders_dataset.csv").unlink()
    with pytest.raises(FileNotFoundError, match="olist_orders_dataset.csv"):
        ol.check_files_exist(tmp_path, ol.FILES)


def test_batch_id_is_stable_and_content_dependent(tmp_path, monkeypatch):
    monkeypatch.delenv("PIPELINE_BATCH_ID", raising=False)
    make_folder(tmp_path)
    first = ol.make_batch_id(tmp_path, ol.FILES)
    assert first == ol.make_batch_id(tmp_path, ol.FILES)
    assert first.startswith("olist_") and len(first) == len("olist_") + 12

    path = tmp_path / "olist_sellers_dataset.csv"
    write_csv(path, ol.FILES[path.name][1], [["x", "y", "z", "w"]])
    assert ol.make_batch_id(tmp_path, ol.FILES) != first


def test_batch_id_overrides(tmp_path, monkeypatch):
    make_folder(tmp_path)
    monkeypatch.setenv("PIPELINE_BATCH_ID", "airflow-run-1")
    assert ol.make_batch_id(tmp_path, ol.FILES) == "airflow-run-1"
    assert ol.make_batch_id(tmp_path, ol.FILES, "manual") == "manual"


def test_skip_geolocation_removes_only_that_file():
    files = ol.selected_files(skip_geolocation=True)
    assert ol.GEOLOCATION_FILE not in files and len(files) == 8
    assert len(ol.selected_files()) == 9


def test_bad_header_stops_before_any_db_access(tmp_path):
    make_folder(tmp_path)
    path = tmp_path / "olist_sellers_dataset.csv"
    write_csv(path, ["wrong"], [["1"]])

    class Boom:
        def raw_connection(self):
            raise AssertionError("database must not be touched")

    with pytest.raises(ValueError, match="olist_sellers_dataset.csv"):
        ol.load_olist(Boom(), tmp_path)


# ---------------------------------------------------------------- integration

@pytest.fixture()
def engine():
    from sqlalchemy import create_engine, text

    engine = create_engine(DB_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS raw CASCADE"))
        for name in ("01_raw_schema.sql", "04_raw_olist.sql"):
            conn.exec_driver_sql((SQL_DIR / name).read_text())
    yield engine
    engine.dispose()


@pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")
def test_load_is_idempotent_against_postgres(engine, tmp_path):
    from sqlalchemy import text

    make_folder(tmp_path, rows_per_file=3)
    # one empty value must be stored as NULL
    path = tmp_path / "olist_orders_dataset.csv"
    cols = ol.FILES[path.name][1]
    write_csv(path, cols, [[f"{c}_{i}" if c != "order_approved_at" else ""
                            for c in cols] for i in range(3)])

    summary, batch_id = ol.load_olist(engine, tmp_path)
    assert all(read == 3 and ins == 3 for read, ins in summary.values())
    assert len(summary) == 9

    again, same_batch = ol.load_olist(engine, tmp_path)
    assert same_batch == batch_id
    assert all(read == 3 and ins == 0 for read, ins in again.values())

    with engine.connect() as conn:
        for table, _ in ol.FILES.values():
            count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()
            assert count == 3, table
        nulls = conn.execute(
            text("SELECT count(*) FROM raw.olist_orders WHERE order_approved_at IS NULL")
        ).scalar()
        assert nulls == 3
        source = conn.execute(
            text("SELECT DISTINCT source_name FROM raw.olist_orders")
        ).scalar()
        assert source == "olist_csv"
