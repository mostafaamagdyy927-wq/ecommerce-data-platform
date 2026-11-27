"""Run the data quality checks against Postgres and store the results.

Usage (from the repo root, with PYTHONPATH=src):
    python -m quality.run_checks
    python -m quality.run_checks --run-id manual-1
    python -m quality.run_checks --fail-on warn
    python -m quality.run_checks --list

Exit code 1 when an error-level check fails, so Airflow marks the task failed.
Results are stored in dwh.dq_check_result, one row per check per run.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from extract.api_client import get_engine
from quality.checks import CHECKS, ERROR, WARN, evaluate, failures, summary

log = logging.getLogger("quality")

RESULT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS dwh.dq_check_result (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL,
    check_name  TEXT NOT NULL,
    severity    TEXT NOT NULL CHECK (severity IN ('error', 'warn')),
    observed    NUMERIC NOT NULL,
    expectation TEXT NOT NULL,
    passed      BOOLEAN NOT NULL,
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, check_name)
)
"""

STORE_SQL = text(
    """
    INSERT INTO dwh.dq_check_result
        (run_id, check_name, severity, observed, expectation, passed)
    VALUES
        (:run_id, :check_name, :severity, :observed, :expectation, :passed)
    ON CONFLICT (run_id, check_name) DO UPDATE
    SET severity    = EXCLUDED.severity,
        observed    = EXCLUDED.observed,
        expectation = EXCLUDED.expectation,
        passed      = EXCLUDED.passed,
        checked_at  = now()
    """
)


def ensure_result_table(engine):
    """Create dwh.dq_check_result if it does not exist yet."""
    with engine.begin() as conn:
        conn.execute(text(RESULT_TABLE_SQL))


def run_checks(engine, run_id):
    """Execute every check, store the results and return them."""
    ensure_result_table(engine)
    results = []
    with engine.begin() as conn:
        for check in CHECKS:
            observed = conn.execute(text(check.sql)).scalar_one()
            results.append(evaluate(check, observed))
        conn.execute(
            STORE_SQL,
            [
                {
                    "run_id": run_id,
                    "check_name": result.check.name,
                    "severity": result.check.severity,
                    "observed": result.observed,
                    "expectation": result.check.expectation,
                    "passed": result.passed,
                }
                for result in results
            ],
        )
    return results


def format_report(run_id, results, fail_on=ERROR):
    """Text report: one line per check, then the summary and the verdict."""
    lines = ["== data quality checks ==", f"run_id: {run_id}", ""]
    lines.extend(result.line() for result in results)
    lines.append("")
    lines.append(summary(results))
    blocking = failures(results, fail_on)
    lines.append(f"RESULT: {'FAILED' if blocking else 'PASSED'} (fail on {fail_on})")
    return "\n".join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run the dwh data quality checks")
    parser.add_argument(
        "--run-id",
        default=None,
        help="label stored with the results (default: manual-<timestamp>)",
    )
    parser.add_argument(
        "--fail-on",
        choices=(ERROR, WARN),
        default=ERROR,
        help="lowest severity that makes the command exit 1 (default: error)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the checks and exit without touching the database",
    )
    return parser.parse_args(argv)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    args = parse_args(argv)

    if args.list:
        for check in CHECKS:
            print(f"{check.severity:<6}{check.name:<30}{check.description}")
        return 0

    run_id = args.run_id or f"manual-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:4]}"
    engine = get_engine()
    try:
        results = run_checks(engine, run_id)
    finally:
        engine.dispose()

    print(format_report(run_id, results, args.fail_on))
    return 1 if failures(results, args.fail_on) else 0


if __name__ == "__main__":
    sys.exit(main())
