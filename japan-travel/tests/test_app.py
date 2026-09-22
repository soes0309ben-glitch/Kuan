import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Purchase


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _csrf_token(client, path):
    resp = client.get(path)
    match = re.search(r'name="csrf_token" value="([^"]+)"', resp.text)
    assert match, f"no csrf token found on {path}"
    return match.group(1)


def test_home_page_ok(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "旅日誌" in resp.text


def test_explore_page_ok(client):
    resp = client.get("/explore")
    assert resp.status_code == 200


def test_explore_page_prefills_query_from_home_search(client):
    resp = client.get("/explore?q=%E4%BA%AC%E9%83%BD")
    assert resp.status_code == 200
    assert 'value="京都"' in resp.text


def test_api_attractions_returns_json(client):
    resp = client.get("/api/attractions")
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert "count" in body
    if body["results"]:
        assert "maps_url" in body["results"][0]


def test_api_attractions_accepts_empty_remote_island_param(client):
    # Regression test: the front end's unchecked "只看離島" checkbox sends
    # remote_island= (empty string), which a plain `bool` query param used
    # to reject with 422 — crashing the explore page's JS on every load.
    resp = client.get("/api/attractions?remote_island=")
    assert resp.status_code == 200
    assert "results" in resp.json()


def test_itineraries_page_ok(client):
    resp = client.get("/itineraries")
    assert resp.status_code == 200


def test_guide_beginner_page_ok(client):
    resp = client.get("/guides/beginner")
    assert resp.status_code == 200
    assert "Visit Japan Web" in resp.text


def test_news_page_shows_setup_notice_without_key(client):
    resp = client.get("/news")
    assert resp.status_code == 200
    assert "NEWSAPI_KEY" in resp.text


def test_admin_dashboard_hidden_from_non_admin(client):
    resp = client.get("/admin")
    assert resp.status_code == 404

    client.post(
        "/register",
        data={
            "csrf_token": _csrf_token(client, "/register"),
            "email": "notadmin@example.com",
            "password": "supersecret1",
        },
        follow_redirects=False,
    )
    resp = client.get("/admin")
    assert resp.status_code == 404


def test_itinerary_detail_shows_flight_price_reference(client):
    resp = client.get("/itineraries")
    itinerary_id = re.search(r"/itineraries/([a-z0-9-]+)", resp.text).group(1)
    resp = client.get(f"/itineraries/{itinerary_id}")
    assert resp.status_code == 200
    assert "來回機票參考價格" in resp.text
    assert "僅為歷史區間概估" in resp.text


def test_register_login_logout_flow(client):
    resp = client.post(
        "/register",
        data={
            "csrf_token": _csrf_token(client, "/register"),
            "email": "traveler@example.com",
            "password": "supersecret1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    resp = client.get("/account/purchases")
    assert resp.status_code == 200
    assert "還沒有解鎖任何行程" in resp.text

    resp = client.post(
        "/logout", data={"csrf_token": _csrf_token(client, "/")}, follow_redirects=False
    )
    assert resp.status_code == 303

    resp = client.post(
        "/login",
        data={
            "csrf_token": _csrf_token(client, "/login"),
            "email": "traveler@example.com",
            "password": "wrong-password",
        },
    )
    assert resp.status_code == 400


def test_register_rejects_duplicate_email(client):
    email = "dup@example.com"
    for _ in range(2):
        resp = client.post(
            "/register",
            data={
                "csrf_token": _csrf_token(client, "/register"),
                "email": email,
                "password": "supersecret1",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 400
    assert "已經註冊過了" in resp.text


def test_login_rejects_wrong_csrf_token(client):
    resp = client.post(
        "/login",
        data={"csrf_token": "not-the-real-token", "email": "x@example.com", "password": "whatever1"},
    )
    assert resp.status_code == 400
    assert "驗證失敗" in resp.text


def test_checkout_requires_login(client):
    resp = client.post(
        "/itineraries/does-not-exist/checkout",
        data={"tier": "economy", "csrf_token": "dummy"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


def test_checkout_without_stripe_key_returns_503_and_no_duplicate_purchase(client):
    client.post(
        "/register",
        data={
            "csrf_token": _csrf_token(client, "/register"),
            "email": "buyer@example.com",
            "password": "supersecret1",
        },
        follow_redirects=False,
    )

    resp = client.get("/itineraries")
    itinerary_id = re.search(r"/itineraries/([a-z0-9-]+)", resp.text)
    assert itinerary_id, "expected at least one itinerary link on /itineraries"
    itinerary_id = itinerary_id.group(1)

    for _ in range(2):
        resp = client.post(
            f"/itineraries/{itinerary_id}/checkout",
            data={"csrf_token": _csrf_token(client, f"/itineraries/{itinerary_id}"), "tier": "economy"},
        )
        assert resp.status_code == 503

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        count = db.query(Purchase).filter(Purchase.itinerary_id == itinerary_id).count()
        assert count == 0
    finally:
        db.close()
