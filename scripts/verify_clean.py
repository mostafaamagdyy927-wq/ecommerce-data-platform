"""Quick check of the clean layer: rows per source, rejects, latest price per source."""

from sqlalchemy import text

from extract.api_client import get_engine

QUERIES = {
    "products and price snapshots per source": """
        SELECT s.source_name,
               count(DISTINCT p.product_key) AS products,
               count(f.product_key)          AS snapshots
        FROM dwh.dim_source s
        LEFT JOIN dwh.dim_product p ON p.source_key = s.source_key
        LEFT JOIN dwh.fact_price_snapshot f ON f.product_key = p.product_key
        GROUP BY s.source_name
        ORDER BY s.source_name
    """,
    "rejected records per source": """
        SELECT source_name, count(*) AS rejected
        FROM dwh.rejected_records
        GROUP BY source_name
        ORDER BY source_name
    """,
}


def main():
    engine = get_engine()
    try:
        with engine.connect() as conn:
            for title, sql in QUERIES.items():
                print(f"\n== {title} ==")
                rows = conn.execute(text(sql)).all()
                if not rows:
                    print("(none)")
                for row in rows:
                    print(tuple(row))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
