from decimal import Decimal

import pytest

from transform.transform_products import (
    RejectedRecord,
    category_label,
    clean_product,
)


def good_product(**overrides):
    product = {
        "id": 1,
        "title": "  Essence   Mascara  ",
        "description": "Great\n mascara",
        "category": "beauty",
        "price": 9.99,
        "discountPercentage": 7.17,
        "rating": 4.94,
        "stock": 5,
        "tags": ["beauty", " mascara ", ""],
        "brand": "Essence",
        "sku": "BEA-ESS-ESS-001",
        "weight": 2,
        "dimensions": {"width": 23.17, "height": 14.43, "depth": 28.01},
        "availabilityStatus": "In Stock",
        "thumbnail": "https://example.com/t.png",
        "meta": {"createdAt": "2025-04-30T09:41:02.053Z"},
    }
    product.update(overrides)
    return product


def test_clean_product_standardizes_fields():
    dim, fact = clean_product(good_product())
    assert dim["source_product_id"] == "1"
    assert dim["title"] == "Essence Mascara"
    assert dim["description"] == "Great mascara"
    assert dim["tags"] == ["beauty", "mascara"]
    assert dim["width"] == Decimal("23.17")
    assert dim["created_at_source"].year == 2025
    assert fact["price"] == Decimal("9.99")
    assert fact["price_after_discount"] == Decimal("9.27")
    assert fact["stock"] == 5


def test_missing_brand_and_category_use_defaults():
    dim, _ = clean_product(good_product(brand=None, category=" "))
    assert dim["brand"] == "Unknown"
    assert dim["category"] == "Unknown"


def test_category_label():
    assert category_label("mens-shirts") == "Mens Shirts"
    assert category_label(None) is None


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"id": None}, "missing id"),
        ({"title": "  "}, "missing title"),
        ({"price": None}, "missing price"),
        ({"price": 0}, "price must be positive"),
        ({"price": -3}, "price must be positive"),
        ({"price": "abc"}, "invalid price"),
        ({"discountPercentage": 120}, "discountPercentage out of range"),
        ({"rating": 7}, "rating out of range"),
        ({"stock": -1}, "stock must not be negative"),
        ({"stock": 2.5}, "invalid stock"),
    ],
)
def test_invalid_records_are_rejected(overrides, reason):
    with pytest.raises(RejectedRecord, match=reason):
        clean_product(good_product(**overrides))


def test_non_object_payload_is_rejected():
    with pytest.raises(RejectedRecord):
        clean_product(["not", "a", "dict"])


def test_optional_fields_may_be_missing():
    dim, fact = clean_product({"id": 7, "title": "Thing", "price": 5})
    assert dim["weight"] is None
    assert dim["tags"] == []
    assert fact["discount_percentage"] is None
    assert fact["price_after_discount"] is None
