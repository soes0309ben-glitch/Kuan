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
    # 測試資料每格只有 11 題，不足 30 題時全部出
    assert len(data["questions"]) == min(30, 11)
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
    assert result["finished"] and result["score"] == result["total"]
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


def test_bank_needs_login_but_not_subscription(db, make_client):
    assert TestClient(app).get("/api/bank").status_code == 401
    client, _ = make_client()
    r = client.get("/api/bank?cat=anime&difficulty=easy")
    assert r.status_code == 200 and r.json()["total"] == 11
    # 免費會員看得到題目和選項，看不到答案
    assert all("answer" not in q and q["q"] for q in r.json()["questions"])
    # PDF 是訂閱會員專屬
    assert client.get("/api/bank/export.pdf").status_code == 402


def test_free_user_sees_answers_only_for_finished_combos(make_client):
    client, _ = make_client()
    play_through(client, start(client).json()["attempt_id"])
    assert all("answer" in q for q in client.get("/api/bank?cat=anime&difficulty=easy").json()["questions"])
    assert all("answer" not in q for q in client.get("/api/bank?cat=anime&difficulty=hard").json()["questions"])


def test_subscriber_sees_all_answers(make_client):
    client, _ = make_client(subscribed=True)
    data = client.get("/api/bank").json()
    assert data["subscribed"] and data["questions"]
    assert all("answer" in q for q in data["questions"])


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


def test_import_with_token(db, monkeypatch):
    from app.config import get_settings
    settings = get_settings()
    client = TestClient(app)
    item = [{"cat": "trivia", "type": "single", "difficulty": "easy", "q": "密碼匯入測試",
             "options": ["對", "錯"], "answer": "對"}]
    # 沒設定 IMPORT_TOKEN：一律拒絕
    assert client.post("/api/admin/import-with-token", json=item, headers={"x-import-token": ""}).status_code == 403
    monkeypatch.setattr(settings, "import_token", "x" * 40)
    assert client.post("/api/admin/import-with-token", json=item, headers={"x-import-token": "wrong"}).status_code == 403
    r = client.post("/api/admin/import-with-token", json=item, headers={"x-import-token": "x" * 40})
    assert r.status_code == 200 and r.json() == {"added": 1, "updated": 0}
    # 太短的密碼視同未啟用
    monkeypatch.setattr(settings, "import_token", "short")
    assert client.post("/api/admin/import-with-token", json=item, headers={"x-import-token": "short"}).status_code == 403


PNG_1PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def test_profile_defaults_and_update(make_client):
    client, _ = make_client()
    me = client.get("/api/me").json()
    assert me["profile"]["frame"] == "none" and me["profile"]["color"] == "pink"
    r = client.post("/api/profile", json={"nickname": "小可愛", "avatar_type": "emoji", "avatar_emoji": "🐰",
                                          "frame": "ribbon", "color": "mint"})
    assert r.status_code == 200, r.text
    p = client.get("/api/me").json()["profile"]
    assert (p["nickname"], p["avatar_emoji"], p["frame"], p["color"]) == ("小可愛", "🐰", "ribbon", "mint")


def test_profile_rejects_bad_values(make_client):
    client, _ = make_client()
    base = {"nickname": "", "avatar_type": "google", "avatar_emoji": "", "frame": "none", "color": "pink"}
    assert client.post("/api/profile", json={**base, "frame": "gold"}).status_code == 400
    assert client.post("/api/profile", json={**base, "color": "black"}).status_code == 400
    assert client.post("/api/profile", json={**base, "nickname": "長" * 21}).status_code == 400
    assert client.post("/api/profile", json={**base, "avatar_type": "emoji"}).status_code == 400
    # 還沒上傳圖片不能選「上傳」
    assert client.post("/api/profile", json={**base, "avatar_type": "upload"}).status_code == 400


def test_avatar_upload(make_client):
    client, _ = make_client()
    r = client.post("/api/profile/avatar", json={"data_url": PNG_1PX})
    assert r.status_code == 200, r.text
    assert r.json()["avatar_type"] == "upload" and r.json()["avatar_url"].startswith("/api/profile/avatar")
    img = client.get("/api/profile/avatar")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    # 偽裝成圖片的檔案、過大的檔案都要擋掉
    fake = "data:image/png;base64," + __import__("base64").b64encode(b"<script>alert(1)</script>").decode()
    assert client.post("/api/profile/avatar", json={"data_url": fake}).status_code == 400
    assert client.post("/api/profile/avatar", json={"data_url": "data:image/svg+xml;base64,PHN2Zz4="}).status_code == 400
    big = "data:image/png;base64," + __import__("base64").b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 400_000).decode()
    assert client.post("/api/profile/avatar", json={"data_url": big}).status_code == 400


def test_avatar_is_private(make_client):
    a, _ = make_client("a@example.com")
    a.post("/api/profile/avatar", json={"data_url": PNG_1PX})
    b, _ = make_client("b@example.com")
    assert b.get("/api/profile/avatar").status_code == 404


def _team_play_all(client, code):
    data = client.get(f"/api/teams/{code}/play").json()
    for q in data["questions"]:
        given = {"single": "對", "short": "富士山", "image": "富士山", "qa": "想法"}[q["type"]]
        assert client.post(f"/api/teams/{code}/answer", json={"question_id": q["id"], "given": given}).status_code == 200
        if q["type"] == "qa":
            client.post(f"/api/teams/{code}/self-grade", json={"question_id": q["id"], "score": 1})


def test_team_flow_and_ranking(make_client):
    owner, _ = make_client("owner@example.com")
    code = owner.post("/api/teams", json={"category": "anime", "difficulty": "easy"}).json()["code"]
    friend, _ = make_client("friend@example.com")
    # 還沒加入不能作答
    assert friend.get(f"/api/teams/{code}/play").status_code == 403
    assert friend.post(f"/api/teams/{code}/join", json={}).status_code == 200
    same_q = [q["id"] for q in owner.get(f"/api/teams/{code}/play").json()["questions"]]
    assert same_q == [q["id"] for q in friend.get(f"/api/teams/{code}/play").json()["questions"]]

    _team_play_all(owner, code)
    view = friend.get(f"/api/teams/{code}").json()
    # 隊友還沒答完：看不到隊長的分數
    assert not view["all_finished"] and all(m["score"] is None for m in view["members"] if m["name"] == "owner")
    data = friend.get(f"/api/teams/{code}/play").json()
    for q in data["questions"]:
        friend.post(f"/api/teams/{code}/answer", json={"question_id": q["id"], "given": "亂答"})
        if q["type"] == "qa":
            friend.post(f"/api/teams/{code}/self-grade", json={"question_id": q["id"], "score": 0})
    view = owner.get(f"/api/teams/{code}").json()
    assert view["all_finished"] and [r["score"] for r in view["ranking"]] == [view["total"], 0]
    assert len(view["breakdown"]) == view["total"]


def test_team_max_three_and_login_required(db, make_client):
    owner, _ = make_client("o@example.com")
    code = owner.post("/api/teams", json={"category": "travel", "difficulty": "hard"}).json()["code"]
    assert TestClient(app).get(f"/api/teams/{code}").status_code == 401
    for email in ("b@example.com", "c@example.com"):
        c, _ = make_client(email)
        assert c.post(f"/api/teams/{code}/join", json={}).status_code == 200
    d, _ = make_client("d@example.com")
    assert d.post(f"/api/teams/{code}/join", json={}).status_code == 409


def test_team_does_not_use_solo_attempt(make_client):
    client, _ = make_client()
    play_through(client, start(client).json()["attempt_id"])
    # 個人已挑戰過，組隊仍可再玩同主題同難度
    assert client.post("/api/teams", json={"category": "anime", "difficulty": "easy"}).status_code == 200
    assert client.post("/api/teams", json={"category": "anime", "difficulty": "easy"}).status_code == 200


def test_teammate_avatar_visible_only_to_teammates(make_client):
    a, _ = make_client("a@example.com")
    a.post("/api/profile/avatar", json={"data_url": PNG_1PX})
    a_id = a.get("/api/me").json()
    code = a.post("/api/teams", json={"category": "anime", "difficulty": "easy"}).json()["code"]
    owner_id = a.get(f"/api/teams/{code}").json()["members"][0]["user_id"]
    stranger, _ = make_client("s@example.com")
    assert stranger.get(f"/api/teams/avatar/{owner_id}").status_code == 404
    mate, _ = make_client("m@example.com")
    mate.post(f"/api/teams/{code}/join", json={})
    assert mate.get(f"/api/teams/avatar/{owner_id}").status_code == 200


def test_owner_deletes_team_member_leaves(make_client):
    owner, _ = make_client("own@example.com")
    code = owner.post("/api/teams", json={"category": "anime", "difficulty": "easy"}).json()["code"]
    mate, _ = make_client("mate@example.com")
    mate.post(f"/api/teams/{code}/join", json={})
    q = mate.get(f"/api/teams/{code}/play").json()["questions"][0]
    mate.post(f"/api/teams/{code}/answer", json={"question_id": q["id"], "given": "對"})
    # 隊員退出：只有自己離開，隊伍還在
    assert mate.post(f"/api/teams/{code}/leave", json={}).json() == {"left": True}
    assert len(owner.get(f"/api/teams/{code}").json()["members"]) == 1
    assert mate.get("/api/teams/mine").json()["teams"] == []
    # 陌生人不能刪
    stranger, _ = make_client("x@example.com")
    assert stranger.post(f"/api/teams/{code}/leave", json={}).status_code == 403
    # 隊長刪除：整個隊伍消失
    assert owner.post(f"/api/teams/{code}/leave", json={}).json() == {"deleted": True}
    assert owner.get(f"/api/teams/{code}").status_code == 404


def _answer_all(client, slug, pick_index, n=0):
    t = client.get(f"/api/psych/{slug}?n={n}").json()
    return client.post(f"/api/psych/{slug}/submit",
                       json={"answers": [{"q": q["id"], "o": pick_index(q)} for q in t["questions"]]})


def test_psych_list_and_no_scores_leaked(db):
    c = TestClient(app)
    tests = c.get("/api/psych").json()["tests"]
    assert {t["slug"] for t in tests} == {"lovebrain", "lovetype", "animal", "type16", "match", "career", "psychopath", "romance", "scent", "cat", "taiwan"}
    t = c.get("/api/psych/lovebrain?n=10").json()
    assert len(t["questions"]) == 10 and all(isinstance(o, str) for q in t["questions"] for o in q["options"])


def test_psych_index_extremes(db):
    c = TestClient(app)
    high = _answer_all(c, "lovebrain", lambda q: 0).json()   # 每題都選最強烈的選項
    low = _answer_all(c, "lovebrain", lambda q: len(q["options"]) - 1).json()
    assert high["index"] == 100 and high["level"]["name"] == "戀愛腦末期"
    assert low["index"] == 0 and low["level"]["name"] == "清醒理智派"
    assert "code" not in high  # 未登入不保存


def test_psych_type16_and_career(db):
    c = TestClient(app)
    r = _answer_all(c, "type16", lambda q: 0).json()
    assert r["type_key"] == "ESTJ" and len(r["dims"]) == 4
    r = _answer_all(c, "type16", lambda q: 1, n=8).json()
    assert len(r["type_key"]) == 4
    r = _answer_all(c, "career", lambda q: 0).json()
    assert len(r["holland"]) == 3 and r["top"][0]["careers"]


def test_psych_rejects_bad_answers(db):
    c = TestClient(app)
    assert c.post("/api/psych/animal/submit", json={"answers": [{"q": 0, "o": 9}]}).status_code == 400
    assert c.post("/api/psych/animal/submit", json={"answers": []}).status_code == 400
    assert c.get("/api/psych/nope").status_code == 404


def test_career_code_survives_saving(make_client):
    # 登入後會加上分享代碼 code，不能蓋掉三碼的興趣代碼
    client, _ = make_client()
    r = _answer_all(client, "career", lambda q: 0).json()
    assert len(r["holland"]) == 3 and set(r["holland"]) <= set("RIASEC") and len(r["code"]) > 3


def test_psych_save_share_and_match(make_client):
    a, _ = make_client("a@example.com")
    ra = _answer_all(a, "match", lambda q: 0).json()
    assert ra["code"]
    shared = TestClient(app).get(f"/api/psych/r/{ra['code']}").json()
    assert shared["type_key"] == ra["type_key"] and "email" not in json.dumps(shared)
    b, _ = make_client("b@example.com")
    t = b.get("/api/psych/match").json()
    rb = b.post("/api/psych/match/submit", json={"with_code": ra["code"],
                "answers": [{"q": q["id"], "o": 0} for q in t["questions"]]}).json()
    assert rb["partner"]["compat"] >= 90  # 答案完全相同，默契很高
    assert len(b.get("/api/psych/me/results").json()["results"]) == 1


def test_psych_illust_admin_only_and_limit(make_client):
    user, _ = make_client("u@example.com")
    assert user.post("/api/admin/psych-illust", json={"slug": "taiwan", "data_url": PNG_1PX}).status_code == 403
    admin, _ = make_client("admin@example.com")
    slugs = ["lovebrain", "lovetype", "animal", "type16", "match"]
    for slug in slugs:
        assert admin.post("/api/admin/psych-illust", json={"slug": slug, "data_url": PNG_1PX}).status_code == 200
    # 第 6 張超過免費上限
    assert admin.post("/api/admin/psych-illust", json={"slug": "career", "data_url": PNG_1PX}).status_code == 409
    # 替換既有的不算新增
    assert admin.post("/api/admin/psych-illust", json={"slug": "match", "data_url": PNG_1PX}).status_code == 200
    tests = {t["slug"]: t for t in TestClient(app).get("/api/psych").json()["tests"]}
    assert tests["lovebrain"]["illust"].startswith("/api/psych/illust/lovebrain") and tests["career"]["illust"] is None
    assert TestClient(app).get("/api/psych/illust/lovebrain").headers["content-type"] == "image/png"
    admin.post("/api/admin/psych-illust/delete", json={"slug": "match"})
    assert admin.post("/api/admin/psych-illust", json={"slug": "career", "data_url": PNG_1PX}).status_code == 200


def test_psych_mix(make_client):
    # 綜合心理測驗：從 8 個測驗各抽題，結果包含每個測驗的類型和 5 個綜合特性
    c = TestClient(app)
    info = c.get("/api/psych").json()["mix"]
    assert info["count"] == 29 and len(info["emojis"]) == 8
    t = c.get("/api/psych/mix").json()
    assert t["fixed"] and len(t["questions"]) == 29 and len({q["id"] for q in t["questions"]}) == 29
    client, _ = make_client("mix@example.com")
    r = client.post("/api/psych/mix/submit", json={"answers": [{"q": q["id"], "o": 0} for q in t["questions"]]}).json()
    assert r["kind"] == "mix" and len(r["parts"]) == 8 and len(r["axes"]) == 5 and r["code"]
    assert next(p for p in r["parts"] if p["slug"] == "type16")["extra"] == "ESTJ"
    assert client.get("/api/psych/me/results").json()["results"][0]["title"] == "綜合心理測驗"
    assert c.post("/api/psych/mix/submit", json={"answers": [{"q": 99001, "o": 0}]}).status_code == 400


def test_psych_romance_and_scent(db):
    # 浪漫症快篩：指數、等級、浪漫之友與解藥；戀愛香氣：類型與最對味的香調
    c = TestClient(app)
    high = _answer_all(c, "romance", lambda q: 0).json()
    assert high["index"] == 100 and high["level"]["name"] == "浪漫症末期"
    assert high["friend"]["name"] and high["type"]["cure"]
    assert _answer_all(c, "romance", lambda q: 3).json()["level"]["name"] == "浪漫陰性（一條線）"
    r = _answer_all(c, "scent", lambda q: 0).json()
    assert r["type"]["name"].endswith("香") and r["friend"]["key"] != r["type_key"]

    r = _answer_all(c, "cat", lambda q: 0).json()
    assert r["type"]["name"].endswith("貓") and r["friend"]["name"].endswith("貓")
