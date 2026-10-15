import json
from urllib.parse import parse_qs

from app.models import Budget, Category, Transaction, User


def texts(msgs) -> str:
    """把回覆訊息（含 Flex）裡所有文字串起來，方便比對。"""
    out = []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("text"), str):
                out.append(node["text"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(msgs)
    return "\n".join(out)


def quick_data(msgs) -> list[dict]:
    items = msgs[-1].get("quickReply", {}).get("items", [])
    return [{k: v[0] for k, v in parse_qs(i["action"].get("data", "")).items()} | {"label": i["action"]["label"]}
            for i in items]


def test_rejects_bad_signature(line):
    r = line.client.post("/line/webhook", content=b'{"events":[]}', headers={"x-line-signature": "bad"})
    assert r.status_code == 400


def test_follow_creates_user_with_default_categories(line, db):
    msgs = line({"type": "follow"})
    assert "小明" in texts(msgs)
    user = db.query(User).one()
    assert user.bot_friend and user.display_name == "小明"
    assert db.query(Category).filter(Category.user_id == user.id).count() > 10


def test_record_auto_category_and_totals(line, db):
    msgs = line.say("午餐 120")
    t = db.query(Transaction).one()
    assert (t.amount, t.kind, t.category.name, t.source) == (120, "expense", "餐飲", "line")
    body = texts(msgs)
    assert "已記錄" in body and "-$120" in body and "餐飲" in body
    line.say("計程車 250")
    assert db.query(Transaction).filter(Transaction.note == "計程車").one().category.name == "交通"
    assert "$370" in texts(line.say("今天"))


def test_income_by_keyword(line, db):
    line.say("薪水 50000")
    t = db.query(Transaction).one()
    assert (t.kind, t.category.name) == ("income", "薪水")
    # 支出關鍵字一樣長時算支出；#分類 優先
    line.say("投資課程 3000")
    assert db.query(Transaction).filter(Transaction.note == "投資課程").one().kind == "expense"
    line.say("退款 300 #購物")
    t = db.query(Transaction).filter(Transaction.note == "退款").one()
    assert (t.kind, t.category.name) == ("expense", "購物")
    line.say("飯店 2400")
    assert db.query(Transaction).filter(Transaction.note == "飯店").one().category.name == "娛樂"


def test_change_category_flip_and_undo_by_postback(line, db):
    msgs = line.say("咖啡 65")
    t = db.query(Transaction).one()
    options = quick_data(msgs)
    shopping = next(o for o in options if o.get("act") == "cat" and "購物" in o["label"])
    line.postback(f"act=cat&t={t.id}&c={shopping['c']}")
    db.expire_all()
    assert db.get(Transaction, t.id).category.name == "購物"

    line.postback(f"act=flip&t={t.id}")
    db.expire_all()
    assert db.get(Transaction, t.id).kind == "income"

    undo = next(o for o in options if o.get("act") == "undo")
    assert "已刪除" in texts(line.postback(f"act=undo&ids={undo['ids']}"))
    assert db.query(Transaction).count() == 0


def test_undo_command_only_removes_last_line_entry(line, db):
    line.say("早餐 60")
    line.say("晚餐 200")
    line.say("復原")
    assert [t.note for t in db.query(Transaction)] == ["早餐"]


def test_cannot_touch_other_users_records(line, db):
    line.say("午餐 120", user="U" + "b" * 32)
    other = db.query(Transaction).one()
    line.say("哈囉")  # 建立 A
    assert "不存在" in texts(line.postback(f"act=del&t={other.id}"))
    assert db.query(Transaction).count() == 1


def test_multiline_and_errors(line, db):
    body = texts(line.say("早餐 65\n午餐 120\n亂打"))
    assert db.query(Transaction).count() == 2
    assert "已記錄 2 筆" in body and "亂打" in body


def test_unknown_text_gets_hint(line, db):
    assert "午餐 120" in texts(line.say("你好"))
    assert db.query(Transaction).count() == 0


def test_budget_command_and_alerts(line, db):
    assert "已設定每月總預算 $1,000" in texts(line.say("預算 1000"))
    assert "「餐飲」預算" in texts(line.say("預算 餐飲 500"))
    assert db.query(Budget).count() == 2
    assert "已用" not in texts(line.say("午餐 300"))
    body = texts(line.say("晚餐 150"))  # 餐飲 450 / 500 → 90%
    assert "「餐飲」預算已用 90%" in body
    body = texts(line.say("宵夜 100"))  # 餐飲 550 → 超支
    assert "「餐飲」預算已超支 $50" in body
    status = texts(line.say("預算"))
    assert "超支" in status and "總預算" in status
    line.say("預算 餐飲 0")
    assert db.query(Budget).count() == 1


def test_month_summary_and_recent(line, db):
    line.say("午餐 120")
    line.say("+3000 獎金")
    body = texts(line.say("本月"))
    assert "$120" in body and "$3,000" in body and "+$2,880" in body
    msgs = line.say("明細")
    assert "最近 10 筆" in texts(msgs)
    assert all(o.get("act") == "del" for o in quick_data(msgs))


def test_reminder_command(line, db):
    line.say("提醒 22")
    user = db.query(User).one()
    assert user.reminder_enabled and user.reminder_hour == 22
    line.say("提醒 關")
    db.expire_all()
    assert not db.query(User).one().reminder_enabled


def test_unfollow_disables_push(line, db):
    line.say("提醒 開")
    line({"type": "unfollow"})
    user = db.query(User).one()
    assert not user.bot_friend and not user.reminder_enabled


def test_group_messages_are_ignored(line, db):
    body = json.dumps({"events": [{"type": "message", "replyToken": "x",
                                   "source": {"type": "group", "groupId": "C1", "userId": "U1"},
                                   "message": {"type": "text", "text": "午餐 120"}}]}).encode()
    import base64
    import hashlib
    import hmac
    sig = base64.b64encode(hmac.new(b"line-secret", body, hashlib.sha256).digest()).decode()
    assert line.client.post("/line/webhook", content=body, headers={"x-line-signature": sig}).status_code == 200
    assert db.query(Transaction).count() == 0
