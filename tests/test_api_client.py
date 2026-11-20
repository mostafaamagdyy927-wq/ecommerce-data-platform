import pytest
import requests

from extract import api_client


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(api_client.time, "sleep", lambda *_: None)


def test_fetch_all_products_follows_pagination(monkeypatch):
    monkeypatch.setattr(api_client, "PAGE_SIZE", 2)
    pages = {
        0: {"products": [{"id": 1}, {"id": 2}], "total": 3},
        2: {"products": [{"id": 3}], "total": 3},
    }

    def fake_get(url, params, **kwargs):
        return FakeResponse(body=pages[params["skip"]])

    monkeypatch.setattr(api_client.requests, "get", fake_get)
    assert [p["id"] for p in api_client.fetch_all_products()] == [1, 2, 3]


def test_retries_on_server_error_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, params, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return FakeResponse(status=503)
        return FakeResponse(body={"products": [], "total": 0})

    monkeypatch.setattr(api_client.requests, "get", fake_get)
    assert api_client.fetch_page(0) == {"products": [], "total": 0}
    assert calls["n"] == 3


def test_does_not_retry_client_errors(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, params, **kwargs):
        calls["n"] += 1
        return FakeResponse(status=404)

    monkeypatch.setattr(api_client.requests, "get", fake_get)
    with pytest.raises(requests.HTTPError):
        api_client.fetch_page(0)
    assert calls["n"] == 1


def test_gives_up_after_max_retries(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, params, **kwargs):
        calls["n"] += 1
        raise requests.ConnectionError("down")

    monkeypatch.setattr(api_client.requests, "get", fake_get)
    with pytest.raises(requests.ConnectionError):
        api_client.fetch_page(0)
    assert calls["n"] == api_client.MAX_RETRIES


def test_retry_after_header_is_honored():
    exc = requests.HTTPError(
        "429", response=FakeResponse(status=429, headers={"Retry-After": "7"})
    )
    assert api_client._retry_delay(exc, 1) == 7


def test_get_engine_fails_fast_without_env(monkeypatch):
    monkeypatch.setattr(api_client, "load_dotenv", lambda *_: None)
    for name in api_client.REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="POSTGRES_USER"):
        api_client.get_engine()


def test_get_engine_uses_host_and_sslmode(monkeypatch):
    monkeypatch.setattr(api_client, "load_dotenv", lambda *_: None)
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_DB", "d")
    monkeypatch.setenv("POSTGRES_HOST", "myserver.postgres.database.azure.com")
    monkeypatch.setenv("POSTGRES_SSLMODE", "require")
    url = api_client.get_engine().url
    assert url.host == "myserver.postgres.database.azure.com"
    assert url.query["sslmode"] == "require"


def test_batch_id_uses_orchestrator_value(monkeypatch):
    monkeypatch.setenv("PIPELINE_BATCH_ID", "run-123")
    assert api_client.make_batch_id() == "run-123"
    monkeypatch.delenv("PIPELINE_BATCH_ID")
    assert api_client.make_batch_id() != "run-123"
