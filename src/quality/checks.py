"""Data quality checks for the clean layer (the `dwh` schema).

A check is one read-only SQL query that returns a single number, plus the range
that number must stay inside. This module is pure Python (it never touches the
database), so the rules can be unit-tested without Postgres.
`quality.run_checks` executes the checks and stores the results.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

ERROR = "error"
WARN = "warn"
SEVERITIES = (ERROR, WARN)


@dataclass(frozen=True)
class Check:
    """One data quality rule."""

    name: str
    severity: str
    description: str
    sql: str
    min_value: Decimal | None = None
    max_value: Decimal | None = None

    @property
    def expectation(self) -> str:
        """Human-readable range, e.g. '>= 3' or '<= 0'."""
        bounds = []
        if self.min_value is not None:
            bounds.append(f">= {self.min_value}")
        if self.max_value is not None:
            bounds.append(f"<= {self.max_value}")
        return " and ".join(bounds) or "any value"


@dataclass(frozen=True)
class CheckResult:
    check: Check
    observed: Decimal
    passed: bool

    def line(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] {self.check.name:<30}"
            f"observed={self.observed:<8}"
            f"expected {self.check.expectation:<12}"
            f"({self.check.severity})"
        )


def evaluate(check: Check, observed) -> CheckResult:
    """Compare one observed value with the range the check allows."""
    value = observed if isinstance(observed, Decimal) else Decimal(str(observed))
    if check.min_value is not None and value < check.min_value:
        return CheckResult(check, value, False)
    if check.max_value is not None and value > check.max_value:
        return CheckResult(check, value, False)
    return CheckResult(check, value, True)


def failures(results, fail_on: str = ERROR):
    """Results that did not pass and are at least as strict as `fail_on`."""
    if fail_on not in SEVERITIES:
        raise ValueError(f"fail_on must be one of {SEVERITIES}, got {fail_on!r}")
    limit = SEVERITIES.index(fail_on)
    return [
        result
        for result in results
        if not result.passed and SEVERITIES.index(result.check.severity) <= limit
    ]


def summary(results) -> str:
    """One line: how many checks ran, passed, failed by severity."""
    failed = [result for result in results if not result.passed]
    errors = [result for result in failed if result.check.severity == ERROR]
    warnings = [result for result in failed if result.check.severity == WARN]
    return (
        f"summary: {len(results)} checks | {len(results) - len(failed)} passed | "
        f"{len(errors)} error(s) | {len(warnings)} warning(s)"
    )


# --- the rules -------------------------------------------------------------
# Every query returns a single number. `error` fails the Airflow task,
# `warn` only shows up in the report.

CHECKS: tuple[Check, ...] = (
    Check(
        name="raw_sources_loaded",
        severity=ERROR,
        description="Each of the three sources has at least one raw batch",
        sql="""
            SELECT (SELECT count(DISTINCT source_name) FROM raw.api_products)
                 + (SELECT count(DISTINCT source_name) FROM raw.scraped_products)
                 + (SELECT count(DISTINCT source_name) FROM raw.olist_products)
        """,
        min_value=Decimal(3),
    ),
    Check(
        name="clean_sources_present",
        severity=ERROR,
        description="dim_source has products for the three sources",
        sql="""
            SELECT count(DISTINCT s.source_name)
            FROM dwh.dim_source s
            JOIN dwh.dim_product p ON p.source_key = s.source_key
        """,
        min_value=Decimal(3),
    ),
    Check(
        name="products_per_source",
        severity=ERROR,
        description="No source ended up with zero products",
        sql="""
            SELECT coalesce(min(n), 0)
            FROM (SELECT count(*) AS n FROM dwh.dim_product GROUP BY source_key) t
        """,
        min_value=Decimal(1),
    ),
    Check(
        name="snapshots_per_source",
        severity=ERROR,
        description="No source ended up with zero price snapshots",
        sql="""
            SELECT coalesce(min(n), 0)
            FROM (
                SELECT count(*) AS n
                FROM dwh.fact_price_snapshot f
                JOIN dwh.dim_product p USING (product_key)
                GROUP BY p.source_key
            ) t
        """,
        min_value=Decimal(1),
    ),
    Check(
        name="unified_view_sources",
        severity=ERROR,
        description="dwh.v_price_history returns all three sources",
        sql="SELECT count(DISTINCT source_name) FROM dwh.v_price_history",
        min_value=Decimal(3),
    ),
    Check(
        name="missing_titles",
        severity=ERROR,
        description="Every API/scraped product has a title (Olist has no product names)",
        sql="""
            SELECT count(*)
            FROM dwh.dim_product p
            JOIN dwh.dim_source s USING (source_key)
            WHERE s.source_name <> 'olist_csv'
              AND (p.title IS NULL OR btrim(p.title) = '')
        """,
        max_value=Decimal(0),
    ),
    Check(
        name="duplicate_products",
        severity=ERROR,
        description="No product is stored twice for one source",
        sql="""
            SELECT count(*)
            FROM (
                SELECT 1
                FROM dwh.dim_product
                GROUP BY source_key, source_product_id
                HAVING count(*) > 1
            ) t
        """,
        max_value=Decimal(0),
    ),
    Check(
        name="invalid_prices",
        severity=ERROR,
        description="Prices are positive and below 1,000,000",
        sql="""
            SELECT count(*)
            FROM dwh.fact_price_snapshot
            WHERE price <= 0 OR price > 1000000
        """,
        max_value=Decimal(0),
    ),
    Check(
        name="discount_above_price",
        severity=ERROR,
        description="Price after discount never exceeds the original price",
        sql="""
            SELECT count(*)
            FROM dwh.fact_price_snapshot
            WHERE price_after_discount IS NOT NULL
              AND price_after_discount > price
        """,
        max_value=Decimal(0),
    ),
    Check(
        name="bad_rating_or_stock",
        severity=ERROR,
        description="Ratings are 0-5 and stock is never negative",
        sql="""
            SELECT count(*)
            FROM dwh.fact_price_snapshot
            WHERE (rating IS NOT NULL AND (rating < 0 OR rating > 5))
               OR (stock IS NOT NULL AND stock < 0)
        """,
        max_value=Decimal(0),
    ),
    Check(
        name="currency_mismatch",
        severity=ERROR,
        description="Each source keeps its own currency (GBP / USD / BRL)",
        sql="""
            SELECT count(*)
            FROM dwh.fact_price_snapshot f
            JOIN dwh.dim_product p USING (product_key)
            JOIN dwh.dim_source s USING (source_key)
            WHERE (s.source_name = 'books_to_scrape' AND f.currency <> 'GBP')
               OR (s.source_name = 'dummyjson_api'   AND f.currency <> 'USD')
               OR (s.source_name = 'olist_csv'       AND f.currency <> 'BRL')
        """,
        max_value=Decimal(0),
    ),
    Check(
        name="currency_format",
        severity=ERROR,
        description="Currency codes are three uppercase letters",
        sql="""
            SELECT count(*)
            FROM dwh.fact_price_snapshot
            WHERE currency !~ '^[A-Z]{3}$'
        """,
        max_value=Decimal(0),
    ),
    Check(
        name="rejected_records_recent",
        severity=WARN,
        description="No record was rejected in the last 7 days",
        sql="""
            SELECT count(*)
            FROM dwh.rejected_records
            WHERE rejected_at >= now() - interval '7 days'
        """,
        max_value=Decimal(0),
    ),
    Check(
        name="stale_sources",
        severity=WARN,
        description="Live sources (API, scraping) have a snapshot from the last 7 days",
        sql="""
            SELECT count(*)
            FROM (
                SELECT max(f.captured_at) AS last_seen
                FROM dwh.fact_price_snapshot f
                JOIN dwh.dim_product p USING (product_key)
                JOIN dwh.dim_source s USING (source_key)
                WHERE s.source_name <> 'olist_csv'
                GROUP BY p.source_key
            ) t
            WHERE last_seen < now() - interval '7 days'
        """,
        max_value=Decimal(0),
    ),
    Check(
        name="products_without_snapshot",
        severity=WARN,
        description="Every API/scraped product has a snapshot (Olist snapshots only sold items)",
        sql="""
            SELECT count(*)
            FROM dwh.dim_product p
            JOIN dwh.dim_source s USING (source_key)
            WHERE s.source_name <> 'olist_csv'
              AND NOT EXISTS (
                  SELECT 1
                  FROM dwh.fact_price_snapshot f
                  WHERE f.product_key = p.product_key
              )
        """,
        max_value=Decimal(0),
    ),
)
