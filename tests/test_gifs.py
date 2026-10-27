"""gifs/ (Klipy proxy)."""
import pytest
import requests

import gifs
from tests import factories

KLIPY_GIFS = [{"id": "1", "slug": "cat", "file": {}}]


@pytest.fixture
def klipy(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            if klipy.status >= 400:
                raise requests.HTTPError("boom")

        def json(self):
            return {"data": {"data": KLIPY_GIFS}}

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if klipy.raises:
            raise klipy.raises
        return FakeResponse()

    klipy.status, klipy.raises, klipy.calls = 200, None, calls
    monkeypatch.setattr(gifs, "KLIPY_API_KEY", "test-key")
    monkeypatch.setattr(gifs.requests, "request", fake_request)
    return klipy


@pytest.fixture
def alice(ctx):
    with ctx():
        return factories.make_user("alice")


def test_requires_login(anon):
    assert anon.get("/api/gifs/trending/").status_code == 401
    assert anon.post("/api/gifs/share/cat/").status_code == 401


def test_trending_returns_the_gif_list_and_uses_the_server_key(login_as, alice, klipy):
    response = login_as(alice).get("/api/gifs/trending/")
    assert response.status_code == 200
    assert response.json["content"] == KLIPY_GIFS
    assert "test-key" in klipy.calls[0]["url"]
    assert "test-key" not in response.get_data(as_text=True)


def test_recent_uses_the_current_user_id(login_as, alice, klipy):
    assert login_as(alice).get("/api/gifs/recent/").status_code == 200
    assert klipy.calls[0]["url"].endswith(f"recent/{alice.id}")


def test_search_forces_the_customer_id_and_filter(login_as, alice, klipy):
    response = login_as(alice).get("/api/gifs/search/?q=cat&customer_id=999&content_filter=off")
    assert response.status_code == 200
    params = klipy.calls[0]["params"]
    assert params["q"] == "cat"
    assert params["customer_id"] == str(alice.id)
    assert params["content_filter"] == "medium"


@pytest.mark.parametrize("query", ["", "   ", "x" * 101])
def test_search_rejects_bad_query(login_as, alice, klipy, query):
    assert login_as(alice).get("/api/gifs/search/", query_string={"q": query}).status_code == 400
    assert klipy.calls == []


def test_share(login_as, alice, klipy):
    response = login_as(alice).post("/api/gifs/share/cat-funny_1/")
    assert response.status_code == 200
    assert klipy.calls[0]["method"] == "POST"
    assert klipy.calls[0]["json"] == {"customer_id": str(alice.id)}


def test_share_rejects_bad_slug(login_as, alice, klipy):
    assert login_as(alice).post("/api/gifs/share/a%3Fb=c/").status_code == 400
    assert klipy.calls == []


def test_klipy_failure_is_a_502_without_the_key(login_as, alice, klipy):
    klipy.raises = requests.ConnectionError("https://api.klipy.com/api/v1/test-key/gifs/trending")
    response = login_as(alice).get("/api/gifs/trending/")
    assert response.status_code == 502
    assert "test-key" not in response.get_data(as_text=True)


def test_not_configured(login_as, alice, klipy, monkeypatch):
    monkeypatch.setattr(gifs, "KLIPY_API_KEY", None)
    assert login_as(alice).get("/api/gifs/trending/").status_code == 503
