from decimal import Decimal

import pytest

from transform.transform_products import RejectedRecord
from transform.transform_scraped import (
    clean_book,
    parse_price,
    parse_rating,
    parse_stock,
)


def test_parse_price_gbp():
    assert parse_price("£51.77") == (Decimal("51.77"), "GBP")


def test_parse_price_with_mojibake_prefix():
    assert parse_price("Â£12.50")[0] == Decimal("12.50")


@pytest.mark.parametrize("bad", [None, "", "free", "£0.00"])
def test_parse_price_rejects(bad):
    with pytest.raises(RejectedRecord):
        parse_price(bad)


def test_parse_rating_words_and_numbers():
    assert parse_rating("Three") == 3
    assert parse_rating(4) == 4
    assert parse_rating(None) is None


def test_parse_rating_out_of_range():
    with pytest.raises(RejectedRecord):
        parse_rating(9)


def test_parse_stock():
    assert parse_stock("In stock (22 available)") == 22
    assert parse_stock("In stock") is None


def test_clean_book_ok():
    dim, fact = clean_book(
        {
            "title": "  A  Light in the Attic ",
            "price": "£51.77",
            "product_url": "http://books.toscrape.com/a.html",
            "rating": "Three",
            "availability": "In stock (22 available)",
            "category": "Poetry",
        }
    )
    assert dim["title"] == "A Light in the Attic"
    assert dim["source_product_id"] == "http://books.toscrape.com/a.html"
    assert dim["category"] == "Poetry"
    assert fact["price"] == Decimal("51.77") and fact["currency"] == "GBP"
    assert fact["rating"] == 3 and fact["stock"] == 22


def test_clean_book_missing_url():
    with pytest.raises(RejectedRecord):
        clean_book({"title": "x", "price": "£1.00"})


def test_clean_book_not_object():
    with pytest.raises(RejectedRecord):
        clean_book("nope")
