"""Unit tests for the data quality rules (no database needed)."""

from decimal import Decimal

import pytest

from quality.checks import (
    CHECKS,
    ERROR,
    SEVERITIES,
    WARN,
    Check,
    evaluate,
    failures,
    summary,
)


def make_check(**overrides):
    values = {"name": "demo", "severity": ERROR, "description": "demo", "sql": "SELECT 1"}
    values.update(overrides)
    return Check(**values)


def test_evaluate_passes_inside_bounds():
    check = make_check(min_value=Decimal(3), max_value=Decimal(10))
    assert evaluate(check, 5).passed
    assert evaluate(check, 3).passed
    assert evaluate(check, 10).passed


def test_evaluate_fails_below_min():
    result = evaluate(make_check(min_value=Decimal(3)), 2)
    assert not result.passed
    assert result.observed == Decimal(2)


def test_evaluate_fails_above_max():
    result = evaluate(make_check(max_value=Decimal(0)), 7)
    assert not result.passed
    assert result.observed == Decimal(7)


def test_evaluate_accepts_int_and_string_values():
    check = make_check(max_value=Decimal(0))
    assert evaluate(check, 0).passed
    assert evaluate(check, "0").passed
    assert not evaluate(check, "1").passed


def test_expectation_text():
    assert make_check(min_value=Decimal(3)).expectation == ">= 3"
    assert make_check(max_value=Decimal(0)).expectation == "<= 0"
    assert make_check(min_value=Decimal(1), max_value=Decimal(5)).expectation == ">= 1 and <= 5"
    assert make_check().expectation == "any value"


def test_result_line_marks_status_and_severity():
    passed = evaluate(make_check(name="missing_titles", max_value=Decimal(0)), 0)
    failed = evaluate(make_check(name="missing_titles", max_value=Decimal(0), severity=WARN), 2)
    assert passed.line().startswith("[PASS] missing_titles")
    assert failed.line().startswith("[FAIL] missing_titles")
    assert "(warn)" in failed.line()


def test_failures_ignore_warnings_by_default():
    results = [
        evaluate(make_check(name="a", severity=ERROR, max_value=Decimal(0)), 1),
        evaluate(make_check(name="b", severity=WARN, max_value=Decimal(0)), 1),
    ]
    assert [result.check.name for result in failures(results)] == ["a"]


def test_failures_with_fail_on_warn():
    results = [
        evaluate(make_check(name="a", severity=ERROR, max_value=Decimal(0)), 1),
        evaluate(make_check(name="b", severity=WARN, max_value=Decimal(0)), 1),
        evaluate(make_check(name="c", severity=WARN, max_value=Decimal(0)), 0),
    ]
    assert [result.check.name for result in failures(results, WARN)] == ["a", "b"]


def test_failures_rejects_unknown_level():
    with pytest.raises(ValueError):
        failures([], "fatal")


def test_summary_counts_pass_error_and_warning():
    results = [
        evaluate(make_check(name="a", severity=ERROR, max_value=Decimal(0)), 0),
        evaluate(make_check(name="b", severity=ERROR, max_value=Decimal(0)), 2),
        evaluate(make_check(name="c", severity=WARN, max_value=Decimal(0)), 1),
    ]
    assert summary(results) == "summary: 3 checks | 1 passed | 1 error(s) | 1 warning(s)"


def test_check_names_are_unique():
    names = [check.name for check in CHECKS]
    assert len(names) == len(set(names))


def test_every_check_has_a_valid_severity():
    assert {check.severity for check in CHECKS} <= set(SEVERITIES)


def test_every_check_is_a_read_only_select():
    for check in CHECKS:
        assert check.sql.strip().upper().startswith("SELECT"), check.name
        assert ";" not in check.sql, f"{check.name}: no trailing semicolon"
        for forbidden in ("INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE"):
            assert forbidden not in check.sql.upper(), f"{check.name} must not {forbidden}"


def test_every_check_has_a_bound_and_a_description():
    for check in CHECKS:
        assert check.min_value is not None or check.max_value is not None, check.name
        assert check.description.strip(), check.name


def test_catalog_covers_counts_nulls_duplicates_prices_and_rejects():
    names = {check.name for check in CHECKS}
    for expected in (
        "raw_sources_loaded",
        "products_per_source",
        "snapshots_per_source",
        "missing_titles",
        "duplicate_products",
        "invalid_prices",
        "rejected_records_recent",
    ):
        assert expected in names
