"""Batch ids must be stable for unchanged input, so a re-run stores nothing twice.

These tests cover the rule the DAG depends on: every source derives its batch id
from the data it just read (API response, books JSON, Olist CSVs), and
PIPELINE_BATCH_ID still overrides that when an orchestrator sets it.
"""

from extract import api_client
from load import books_loader


def test_api_batch_id_is_stable_for_the_same_products(monkeypatch):
    monkeypatch.delenv("PIPELINE_BATCH_ID", raising=False)
    products = [{"id": 1, "title": "a", "price": 10}, {"id": 2, "title": "b", "price": 20}]
    assert api_client.make_batch_id(products) == api_client.make_batch_id(products)
    assert api_client.make_batch_id(products).startswith("api_")


def test_api_batch_id_ignores_key_and_page_order(monkeypatch):
    monkeypatch.delenv("PIPELINE_BATCH_ID", raising=False)
    first = [{"id": 1, "price": 10}, {"id": 2, "price": 20}]
    second = [{"price": 20, "id": 2}, {"price": 10, "id": 1}]
    assert api_client.make_batch_id(first) == api_client.make_batch_id(second)


def test_api_batch_id_changes_when_the_data_changes(monkeypatch):
    monkeypatch.delenv("PIPELINE_BATCH_ID", raising=False)
    cheap = [{"id": 1, "price": 10}]
    pricey = [{"id": 1, "price": 11}]
    assert api_client.make_batch_id(cheap) != api_client.make_batch_id(pricey)


def test_api_batch_id_honours_the_orchestrator(monkeypatch):
    monkeypatch.setenv("PIPELINE_BATCH_ID", "run-1")
    assert api_client.make_batch_id([{"id": 1}]) == "run-1"


def test_books_batch_id_is_stable_and_content_based(monkeypatch):
    monkeypatch.delenv("PIPELINE_BATCH_ID", raising=False)
    books = [{"title": "t", "price": "£1.00", "product_url": "http://example.test/1"}]
    batch_id = books_loader.make_batch_id(books)
    assert batch_id == books_loader.make_batch_id(books)
    assert batch_id.startswith("books_")
    other = [{"title": "other", "price": "£1.00", "product_url": "http://example.test/1"}]
    assert batch_id != books_loader.make_batch_id(other)
    reordered = [
        {"product_url": "http://example.test/2", "price": "£2.00", "title": "u"},
        {"product_url": "http://example.test/1", "price": "£1.00", "title": "t"},
    ]
    shuffled = list(reversed(reordered))
    assert books_loader.make_batch_id(reordered) == books_loader.make_batch_id(shuffled)


def test_books_batch_id_honours_the_orchestrator(monkeypatch):
    monkeypatch.setenv("PIPELINE_BATCH_ID", "run-1")
    assert books_loader.make_batch_id([]) == "run-1"
