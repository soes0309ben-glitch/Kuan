import datetime

import pytest

from app.parser import parse_message

TODAY = datetime.date(2026, 10, 15)


def one(text):
    r = parse_message(text, TODAY)
    assert not r.command and not r.errors and len(r.entries) == 1, r
    return r.entries[0]


@pytest.mark.parametrize("text,amount,note", [
    ("午餐 120", 120, "午餐"),
    ("120 午餐", 120, "午餐"),
    ("計程車250", 250, "計程車"),
    ("早餐 $65元", 65, "早餐"),
    ("ＮＴ＄１２０ 晚餐", 120, "晚餐"),
    ("房租 15,000", 15000, "房租"),
    ("耳機 1.2k", 1200, "耳機"),
    ("機票 1.5萬", 15000, "機票"),
    ("7-11 咖啡 45", 45, "7-11 咖啡"),
    ("iPhone 16 32900", 32900, "iPhone 16"),
    ("午餐　１２０", 120, "午餐"),
])
def test_amount_and_note(text, amount, note):
    e = one(text)
    assert (e.amount, e.note, e.occurred_on) == (amount, note, TODAY)


@pytest.mark.parametrize("text,date", [
    ("昨天 晚餐 300", datetime.date(2026, 10, 14)),
    ("前天 晚餐 300", datetime.date(2026, 10, 13)),
    ("10/3 電影 350", datetime.date(2026, 10, 3)),
    ("2026/1/2 電影 350", datetime.date(2026, 1, 2)),
    ("3月5日 房租 15000", datetime.date(2026, 3, 5)),
    # 沒寫年份又比今天晚 → 去年
    ("12/30 聚餐 800", datetime.date(2025, 12, 30)),
])
def test_dates(text, date):
    assert one(text).occurred_on == date


def test_kind_markers_and_category_tag():
    assert one("+50000 薪水").kind == "income"
    assert one("收入 獎金 3000").kind == "income"
    assert one("-120 早餐").kind == "expense"
    assert one("薪水 50000").kind is None  # 交給分類關鍵字判斷
    e = one("咖啡 65 #餐飲")
    assert (e.note, e.category_hint) == ("咖啡", "餐飲")


def test_errors_and_multiline():
    assert parse_message("午餐", TODAY).errors
    assert "不存在" in parse_message("2/30 午餐 5", TODAY).errors[0]
    assert parse_message("午餐 0", TODAY).errors
    r = parse_message("早餐 65\n晚餐 200\n亂打", TODAY)
    assert [e.amount for e in r.entries] == [65, 200] and len(r.errors) == 1


def test_commands():
    assert parse_message("本月", TODAY).command.name == "month"
    assert parse_message("說明", TODAY).command.name == "help"
    c = parse_message("預算 餐飲 5000", TODAY).command
    assert (c.name, c.args) == ("budget", ["餐飲", "5000"])
    # 「今天 午餐 120」是記帳，不是查詢今天
    r = parse_message("今天 午餐 120", TODAY)
    assert r.command is None and r.entries[0].amount == 120
