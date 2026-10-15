import datetime

from fastapi.testclient import TestClient

from app import ledger
from app.main import app
from app.models import ReminderLog, Transaction, User


def test_requires_login(db):
    c = TestClient(app)
    assert c.get("/api/me").json() == {"user": None}
    assert c.get("/api/summary").status_code == 401
    assert c.post("/api/transactions", json={"amount": 1}).status_code == 401


def test_magic_link_is_single_use(line, db):
    uri = line.say("網頁")[0]["contents"]["footer"]["contents"][0]["action"]["uri"]
    path = uri.replace("https://expense.example.com", "")
    c = TestClient(app, base_url="https://expense.example.com")
    assert c.get(path, follow_redirects=False).headers["location"] == "/"
    assert c.get("/api/me").json()["user"]["name"] == "小明"
    c2 = TestClient(app, base_url="https://expense.example.com")
    assert c2.get(path, follow_redirects=False).headers["location"] == "/?login=expired"


def test_web_sees_line_entries_and_crud(web, line, db):
    line.say("午餐 120")
    month = web.get("/api/me").json()["user"]["current_month"]
    rows = web.get("/api/transactions").json()["transactions"]
    assert [(r["note"], r["amount"], r["source"]) for r in rows] == [("午餐", 120, "line")]

    cats = web.get("/api/categories").json()["categories"]
    food = next(c for c in cats if c["name"] == "餐飲")
    salary = next(c for c in cats if c["name"] == "薪水")
    today = ledger.today().isoformat()
    r = web.post("/api/transactions", json={"kind": "income", "amount": 40000, "category_id": salary["id"],
                                             "note": "十月薪水", "date": today})
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    # 分類與收支類型不一致要擋
    assert web.put(f"/api/transactions/{tid}", json={"kind": "expense", "amount": 1,
                                                       "category_id": salary["id"]}).status_code == 422
    assert web.put(f"/api/transactions/{tid}", json={"kind": "income", "amount": 45000, "category_id": salary["id"],
                                                       "note": "十月薪水", "date": today}).json()["amount"] == 45000

    s = web.get(f"/api/summary?month={month}").json()
    assert (s["expense"], s["income"], s["balance"]) == (120, 45000, 44880)
    assert s["by_category"][0]["name"] == "薪水"
    assert sum(d["expense"] for d in s["daily"]) == 120

    assert len(web.get("/api/transactions?q=薪水").json()["transactions"]) == 1
    assert len(web.get(f"/api/transactions?category_id={food['id']}").json()["transactions"]) == 1
    assert web.delete(f"/api/transactions/{tid}").json() == {"ok": True}
    assert len(web.get("/api/transactions").json()["transactions"]) == 1


def test_mutations_require_json(web):
    assert web.post("/api/transactions", data={"amount": "1"}).status_code == 415


def test_other_users_data_is_hidden(web, line, db):
    line.say("午餐 120", user="U" + "b" * 32)
    other = db.query(Transaction).one()
    assert web.get("/api/transactions").json()["transactions"] == []
    assert web.delete(f"/api/transactions/{other.id}").status_code == 404
    assert web.put(f"/api/transactions/{other.id}", json={"amount": 1}).status_code == 404


def test_categories_crud_and_keywords_used_by_bot(web, line, db):
    r = web.post("/api/categories", json={"kind": "expense", "name": "健身", "icon": "🏋️",
                                           "keywords": ["健身房", "蛋白粉"]})
    assert r.status_code == 200
    cid = r.json()["id"]
    assert web.post("/api/categories", json={"kind": "expense", "name": "健身"}).status_code == 409
    line.say("蛋白粉 1200")
    assert db.query(Transaction).one().category.name == "健身"
    assert web.delete(f"/api/categories/{cid}").json() == {"ok": True}
    names = [c["name"] for c in web.get("/api/categories").json()["categories"]]
    assert "健身" not in names
    # 封存後舊紀錄仍保留，可再建立同名分類（會復原）
    assert web.post("/api/categories", json={"kind": "expense", "name": "健身"}).json()["id"] == cid


def test_budgets_and_trend(web, line):
    line.say("午餐 900")
    cats = web.get("/api/categories").json()["categories"]
    food = next(c for c in cats if c["name"] == "餐飲")
    salary = next(c for c in cats if c["name"] == "薪水")
    assert web.post("/api/budgets", json={"amount": 10000}).status_code == 200
    assert web.post("/api/budgets", json={"category_id": food["id"], "amount": 1000}).status_code == 200
    assert web.post("/api/budgets", json={"category_id": salary["id"], "amount": 1000}).status_code == 422
    budgets = web.get("/api/budgets").json()["budgets"]
    assert budgets[0]["name"] == "總預算"
    assert next(b for b in budgets if b["name"] == "餐飲")["ratio"] == 0.9
    t = web.get("/api/trend?months=3").json()["months"]
    assert len(t) == 3 and t[-1]["expense"] == 900


def test_month_start_day(web, db):
    user = db.query(User).one()
    user.month_start_day = 25
    assert ledger.period_bounds(user, "2026-10") == (datetime.date(2026, 10, 25), datetime.date(2026, 11, 25))
    assert ledger.period_key(user, datetime.date(2026, 10, 24)) == "2026-09"
    assert ledger.period_key(user, datetime.date(2026, 1, 3)) == "2025-12"
    assert web.post("/api/me/settings", json={"month_start_day": 30}).status_code == 422
    assert web.post("/api/me/settings", json={"month_start_day": 5, "reminder_enabled": True}).status_code == 200


def test_csv_export(web, line):
    line.say("=cmd 50")
    r = web.get("/api/export.csv")
    assert r.status_code == 200 and r.text.startswith("﻿日期")
    assert "'=cmd" in r.text


def test_cron_reminder_once_per_day(line, db, monkeypatch):
    line.say("提醒 開")
    user = db.query(User).one()
    now = datetime.datetime.now(ledger.get_settings().tz)
    user.reminder_hour = now.hour
    db.commit()
    c = line.client
    assert c.post("/cron/hourly").status_code == 403
    r = c.post("/cron/hourly", headers={"x-cron-token": "cron-token"})
    assert r.json()["sent"]["reminder"] == 1
    r = c.post("/cron/hourly", headers={"x-cron-token": "cron-token"})
    assert r.json()["sent"]["reminder"] == 0
    assert db.query(ReminderLog).count() >= 1


def test_cron_skips_users_who_recorded_today(line, db):
    line.say("提醒 開")
    line.say("午餐 100")
    user = db.query(User).one()
    user.reminder_hour = datetime.datetime.now(ledger.get_settings().tz).hour
    db.commit()
    r = line.client.post("/cron/hourly", headers={"x-cron-token": "cron-token"})
    assert r.json()["sent"]["reminder"] == 0
