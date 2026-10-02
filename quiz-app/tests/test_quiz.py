import json
import time

import stripe
from fastapi.testclient import TestClient

from app.catalog import check_short
from app.main import app
from app.models import User


def start(client, cat="anime", diff="easy"):
    return client.post("/api/attempts", json={"category": cat, "difficulty": diff})


def play_through(client, attempt_id, *, correct=True):
    data = client.get(f"/api/attempts/{attempt_id}").json()
    for q in data["questions"]:
        if correct:
            given = {"single": "對", "short": "富士山", "image": "富士山", "qa": "我的想法"}[q["type"]]
        else:
            given = "亂答"
        r = client.post(f"/api/attempts/{attempt_id}/answer", json={"question_id": q["id"], "given": given})
        assert r.status_code == 200, r.text
        if q["type"] == "qa":
            r = client.post(f"/api/attempts/{attempt_id}/self-grade",
                            json={"question_id": q["id"], "score": 1 if correct else 0})
            assert r.status_code == 200, r.text
    return client.get(f"/api/attempts/{attempt_id}").json()


def test_requires_login(db):
    assert TestClient(app).post("/api/attempts", json={"category": "anime", "difficulty": "easy"}).status_code == 401


def test_questions_hide_answers(make_client):
    client, _ = make_client()
    aid = start(client).json()["attempt_id"]
    data = client.get(f"/api/attempts/{aid}").json()
    assert len(data["questions"]) == 10
    for q in data["questions"]:
        assert "answer" not in q and "accept" not in q and "ref" not in q
        if q["img"]:
            assert q["img"].startswith("/api/media/") and "fuji" not in q["img"]
    assert {q["difficulty"] for q in data["questions"]} == {"easy"}


def test_one_attempt_per_category_and_difficulty(make_client):
    client, _ = make_client()
    aid = start(client).json()["attempt_id"]
    # 未完成前再按開始：回到同一場，不會換題
    assert start(client).json() == {"attempt_id": aid, "resumed": True}
    result = play_through(client, aid)
    assert result["finished"] and result["score"] == 10
    assert start(client).status_code == 409
    # 其他難度、其他主題仍可挑戰
    assert start(client, "anime", "hard").status_code == 200
    assert start(client, "travel", "easy").status_code == 200


def test_cannot_answer_twice(make_client):
    client, _ = make_client()
    aid = start(client).json()["attempt_id"]
    q = client.get(f"/api/attempts/{aid}").json()["questions"][0]
    assert client.post(f"/api/attempts/{aid}/answer", json={"question_id": q["id"], "given": "亂答"}).status_code == 200
    assert client.post(f"/api/attempts/{aid}/answer", json={"question_id": q["id"], "given": "對"}).status_code == 409


def test_wrong_answers_score_zero(make_client):
    client, _ = make_client()
    aid = start(client).json()["attempt_id"]
    assert play_through(client, aid, correct=False)["score"] == 0


def test_cannot_touch_other_users_attempt(make_client):
    a, _ = make_client("a@example.com")
    aid = start(a).json()["attempt_id"]
    b, _ = make_client("b@example.com")
    assert b.get(f"/api/attempts/{aid}").status_code == 404


def test_json_required_for_mutations(make_client):
    client, _ = make_client()
    assert client.post("/api/attempts", data={"category": "anime", "difficulty": "easy"}).status_code == 415


def test_short_answer_matching():
    assert check_short("富士山", ["富士山"])
    assert check_short(" 是富士山！", ["富士山"])
    assert check_short("ＦＵＪＩ", ["fuji"])
    assert check_short("臺灣黑熊", ["台灣黑熊"])
    assert not check_short("不是明", ["明"])
    assert not check_short("", ["明"])


def test_bank_requires_subscription(make_client):
    client, _ = make_client()
    assert client.get("/api/bank").status_code == 402
    assert client.get("/api/bank/export.pdf").status_code == 402


def test_bank_reveals_only_played_combos(make_client):
    client, _ = make_client(subscribed=True)
    data = client.get("/api/bank?cat=anime&difficulty=easy").json()
    assert data["total"] == 11 and all("answer" not in q for q in data["questions"])
    play_through(client, start(client).json()["attempt_id"])
    assert all("answer" in q for q in client.get("/api/bank?cat=anime&difficulty=easy").json()["questions"])
    assert all("answer" not in q for q in client.get("/api/bank?cat=anime&difficulty=hard").json()["questions"])


def test_pdf_export(make_client):
    client, _ = make_client(subscribed=True)
    r = client.get("/api/bank/export.pdf?cat=travel")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def _signed(payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    ts = int(time.time())
    sig = stripe.WebhookSignature._compute_signature(f"{ts}.{body.decode()}", "whsec_test")
    return body, f"t={ts},v1={sig}"


def test_webhook_updates_subscription(make_client, db):
    client, uid = make_client("sub@example.com")
    event = {
        "id": "evt_1", "object": "event", "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_1", "object": "subscription", "customer": "cus_sub@example.com",
                            "status": "active", "items": {"data": [{"current_period_end": int(time.time()) + 86400}]}}},
    }
    body, sig = _signed(event)
    r = client.post("/stripe/webhook", content=body, headers={"stripe-signature": sig})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(User, uid).is_subscribed

    event["data"]["object"]["status"] = "canceled"
    body, sig = _signed(event)
    client.post("/stripe/webhook", content=body, headers={"stripe-signature": sig})
    db.expire_all()
    assert not db.get(User, uid).is_subscribed


def test_webhook_rejects_bad_signature(make_client):
    client, _ = make_client()
    assert client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=bad"}).status_code == 400


def test_admin_only(make_client):
    client, _ = make_client()
    assert client.get("/api/admin/stats").status_code == 403
    admin, _ = make_client("admin@example.com")
    assert admin.get("/api/admin/stats").json()["questions"] == 66
    bad = [{"cat": "anime", "type": "single", "difficulty": "easy", "q": "x", "options": ["a", "b"], "answer": "c"}]
    assert admin.post("/api/admin/import", json=bad).status_code == 400


def test_bank_does_not_leak_answer_by_option_order(make_client, db):
    """題庫檔裡正解都寫在第一個選項；總覽必須打亂，否則沒挑戰也看得出答案。"""
    from app.catalog import import_questions
    import_questions(db, [{"cat": "anime", "type": "single", "difficulty": "hard", "q": f"順序測試{i}",
                           "options": ["正解", "錯A", "錯B", "錯C"], "answer": "正解"} for i in range(20)])
    client, _ = make_client(subscribed=True)
    qs = [q for q in client.get("/api/bank?cat=anime&difficulty=hard&q=順序測試").json()["questions"]]
    assert len(qs) == 20
    assert any(q["options"][0] != "正解" for q in qs)
    # 同一題每次看到的順序一樣
    again = {q["id"]: q["options"] for q in client.get("/api/bank?cat=anime&difficulty=hard&q=順序測試").json()["questions"]}
    assert all(again[q["id"]] == q["options"] for q in qs)


def test_google_redirect_uses_real_host_when_base_url_is_wrong(db, monkeypatch):
    """BASE_URL 填錯（多貼一段）時，回呼網址仍要用實際網址，否則 Google 回 redirect_uri_mismatch。"""
    from urllib.parse import parse_qs, urlsplit

    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "test.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "base_url", "https://quiz.example.comcom.example.com")
    client = TestClient(app, base_url="http://quiz.example.com")
    r = client.get("/auth/google/login", headers={"x-forwarded-proto": "https"}, follow_redirects=False)
    assert r.status_code == 303
    redirect_uri = parse_qs(urlsplit(r.headers["location"]).query)["redirect_uri"][0]
    assert redirect_uri == "https://quiz.example.com/auth/google/callback"

    # BASE_URL 正確時照用 BASE_URL
    monkeypatch.setattr(settings, "base_url", "https://quiz.example.com/")
    r = client.get("/auth/google/login", follow_redirects=False)
    assert parse_qs(urlsplit(r.headers["location"]).query)["redirect_uri"][0] == "https://quiz.example.com/auth/google/callback"
