"""Run the clean layer for all three sources, in order.

1. sql/08_clean_sources.sql  (register scraping source + unified view)
2. API      -> transform_products   (latest batch)
3. Scraping -> transform_scraped    (latest batch)
4. Olist    -> sql/05_stg_olist.sql then sql/06_clean_olist.sql

A source with no raw data yet is skipped with a warning, not an error.
Every step is idempotent, so the whole script can be re-run.
"""

import logging
from pathlib import Path

from extract.api_client import get_engine
from transform import transform_products, transform_scraped

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
log = logging.getLogger("run_all")


def run_sql_file(engine, name):
    sql = (SQL_DIR / name).read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(sql)
        raw.commit()
    finally:
        raw.close()
    log.info("applied %s", name)

def run_python_source(engine, module, label):
    with engine.begin() as conn:
        batch_id = module.latest_batch_id(conn)
        if batch_id is None:
            log.warning("%s: no raw batch yet, skipped", label)
            return None
        result = module.transform_batch(conn, batch_id)
    log.info("%s: %s", label, result)
    return result


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    engine = get_engine()
    try:
        run_sql_file(engine, "08_clean_sources.sql")
        run_python_source(engine, transform_products, "api")
        run_python_source(engine, transform_scraped, "scraping")
        run_sql_file(engine, "05_stg_olist.sql")
        run_sql_file(engine, "06_clean_olist.sql")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
