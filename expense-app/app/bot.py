"""LINE 機器人：把使用者的訊息變成記帳或查詢，組出要回覆的訊息。

handle_* 只負責回傳訊息清單（不直接呼叫 LINE API），方便測試。
"""

import datetime
from urllib.parse import parse_qs, urlencode

from sqlalchemy.orm import Session

from app import line_api as L
from app.categories import active_categories, find_category
from app.config import get_settings
from app.ledger import (
    add_entry,
    budget_alerts,
    budget_status,
    period_bounds,
    period_key,
    set_budget,
    shift_key,
    spent,
    summarize,
    today,
    week_bounds,
)
from app.models import EXPENSE, INCOME, Category, Transaction, User
from app.parser import Command, parse_message
from app.users import create_login_link

INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
TRACK = "#e1e0d9"
SERIES = "#2a78d6"
EXPENSE_INK = "#c03030"
INCOME_INK = "#006300"
STATUS = {"good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b"}

HELP_TEXT = """📒 LINE 記帳本使用說明

【記一筆】直接傳「內容 金額」
・午餐 120、計程車250、120 早餐
・昨天 晚餐 300、10/3 電影 350
・+50000 薪水、收入 獎金 3000
・機票 1.5萬、耳機 1.2k
・咖啡 65 #餐飲（用 # 指定分類）
・一次傳多行，每行記一筆

【查詢】
今天｜昨天｜本週｜本月｜上月｜明細

【預算】
預算 → 看使用狀況
預算 20000 → 設定每月總預算
預算 餐飲 6000 → 設定分類預算（0 為取消）

【其他】
復原 → 刪除剛剛在 LINE 記的那筆
分類 → 看有哪些分類
提醒 開／提醒 關／提醒 21 → 每晚提醒記帳
網頁 → 取得網頁版登入連結（看圖表、編輯、匯出）"""

MAIN_QUICK = [
    L.qr_message("📊 本月"),
    L.qr_message("📅 今天", "今天"),
    L.qr_message("🧾 明細", "明細"),
    L.qr_message("💰 預算", "預算"),
    L.qr_message("🌐 網頁", "網頁"),
    L.qr_message("❓ 說明", "說明"),
]


def money(n: int) -> str:
    return f"${n:,}"


def _txt(text: str, **kw) -> dict:
    return {"type": "text", "text": text, "wrap": True, **kw}


def _row(left: str, right: str, right_color: str = INK, bold: bool = False) -> dict:
    return {
        "type": "box", "layout": "horizontal", "contents": [
            _txt(left, size="sm", color=INK_2, flex=3),
            _txt(right, size="sm", color=right_color, align="end", flex=4, weight="bold" if bold else "regular"),
        ],
    }


def _bar(ratio: float, color: str) -> dict:
    pct = max(0, min(100, round(ratio * 100)))
    fill = {"type": "box", "layout": "vertical", "contents": [], "height": "6px",
            "backgroundColor": color, "cornerRadius": "3px", "width": f"{max(pct, 1)}%"}
    return {"type": "box", "layout": "vertical", "contents": [fill], "height": "6px",
            "backgroundColor": TRACK, "cornerRadius": "3px", "margin": "sm"}


def _status_of(ratio: float) -> tuple[str, str]:
    if ratio >= 1:
        return STATUS["critical"], "🔴 超支"
    if ratio >= 0.8:
        return STATUS["warning"], "🟡 注意"
    return STATUS["good"], "🟢 正常"


def _bubble(title: str, subtitle: str, body: list[dict], footer: list[dict] | None = None) -> dict:
    bubble = {
        "type": "bubble",
        "header": {"type": "box", "layout": "vertical", "paddingBottom": "md", "contents": [
            _txt(title, weight="bold", size="lg", color=INK),
            _txt(subtitle, size="xs", color=MUTED),
        ]},
        "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": body},
    }
    if footer:
        bubble["footer"] = {"type": "box", "layout": "vertical", "spacing": "sm", "contents": footer}
    return bubble


def _message_button(label: str, text: str) -> dict:
    return {"type": "button", "style": "link", "height": "sm", "action": {"type": "message", "label": label, "text": text}}


# ---------- 記帳 ----------

def _signed(t: Transaction) -> tuple[str, str]:
    return (f"-{money(t.amount)}", EXPENSE_INK) if t.kind == EXPENSE else (f"+{money(t.amount)}", INCOME_INK)


def recorded_message(db: Session, user: User, txns: list[Transaction], errors: list[str]) -> list[dict]:
    day = today()
    start, end = period_bounds(user, period_key(user, day))
    month_spent = spent(db, user, start, end)
    today_spent = spent(db, user, day, day + datetime.timedelta(days=1))

    body: list[dict] = []
    if len(txns) == 1:
        t = txns[0]
        amount, color = _signed(t)
        body += [
            _txt(amount, size="xxl", weight="bold", color=color),
            _row("分類", f"{t.category.icon} {t.category.name}"),
            _row("內容", t.note or "（無）"),
            _row("日期", t.occurred_on.strftime("%Y/%m/%d") + ("" if t.occurred_on == day else " ⏪")),
        ]
    else:
        for t in txns:
            amount, color = _signed(t)
            body.append({"type": "box", "layout": "horizontal", "contents": [
                _txt(f"{t.category.icon} {t.note or t.category.name}", size="sm", color=INK, flex=5),
                _txt(amount, size="sm", color=color, align="end", flex=3, weight="bold"),
            ]})
    body.append({"type": "separator", "margin": "lg"})
    body.append(_row("今日支出", money(today_spent)))
    body.append(_row("本期支出", money(month_spent), bold=True))
    alerts = budget_alerts(db, user, txns)
    for a in alerts:
        body.append(_txt(a, size="sm", color=INK, margin="sm"))
    for e in errors:
        body.append(_txt(f"⚠️ 沒記到 {e}", size="xs", color=MUTED))

    title = "✅ 已記錄" if len(txns) == 1 else f"✅ 已記錄 {len(txns)} 筆"
    quick = []
    if len(txns) == 1:
        t = txns[0]
        for c in active_categories(db, user, t.kind):
            if c.id != t.category_id and len(quick) < 8:
                quick.append(L.qr_postback(f"{c.icon}{c.name}", urlencode({"act": "cat", "t": t.id, "c": c.id}),
                                           f"改成「{c.name}」"))
        if t.kind == EXPENSE:
            quick.append(L.qr_postback("💵 其實是收入", urlencode({"act": "flip", "t": t.id}), "改成收入"))
        else:
            quick.append(L.qr_postback("💸 其實是支出", urlencode({"act": "flip", "t": t.id}), "改成支出"))
    quick.append(L.qr_postback("↩️ 復原", urlencode({"act": "undo", "ids": ",".join(str(t.id) for t in txns)}), "復原"))
    quick.append(L.qr_message("📊 本月"))
    alt = "、".join(f"{t.note or t.category.name} {_signed(t)[0]}" for t in txns)
    return [L.flex(f"已記錄：{alt}", _bubble(title, "點下方按鈕可改分類或復原", body), quick)]


# ---------- 查詢 ----------

def summary_message(db: Session, user: User, title: str, start: datetime.date, end: datetime.date,
                    with_budget: bool = False) -> list[dict]:
    s = summarize(db, user, start, end)
    last_day = end - datetime.timedelta(days=1)
    subtitle = start.strftime("%Y/%m/%d") + ("" if start == last_day else f" – {last_day.strftime('%m/%d')}")
    body: list[dict] = [
        _row("支出", money(s["expense"]), EXPENSE_INK, bold=True),
        _row("收入", money(s["income"]), INCOME_INK, bold=True),
        _row("結餘", ("+" if s["balance"] >= 0 else "-") + money(abs(s["balance"])), INK, bold=True),
    ]
    expenses = [c for c in s["by_category"] if c["kind"] == EXPENSE]
    if expenses:
        body.append({"type": "separator", "margin": "lg"})
        body.append(_txt("支出分類", size="xs", color=MUTED, margin="md"))
        top = expenses[:5]
        if len(expenses) > 5:
            rest = expenses[5:]
            top.append({"name": "其他分類", "icon": "…", "amount": sum(c["amount"] for c in rest),
                        "count": sum(c["count"] for c in rest)})
        for c in top:
            ratio = c["amount"] / s["expense"] if s["expense"] else 0
            body.append({"type": "box", "layout": "vertical", "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    _txt(f"{c['icon']} {c['name']}", size="sm", color=INK, flex=4),
                    _txt(f"{money(c['amount'])}・{ratio:.0%}", size="sm", color=INK_2, align="end", flex=4),
                ]},
                _bar(ratio, SERIES),
            ]})
    elif not s["count"]:
        body.append(_txt("這段期間還沒有紀錄，傳「午餐 120」試試看！", size="sm", color=INK_2))

    if with_budget:
        body += _budget_rows(db, user, start, end)
    footer = [_message_button("🌐 看完整報表", "網頁")]
    return [L.flex(f"{title}：支出 {money(s['expense'])}、收入 {money(s['income'])}",
                   _bubble(title, subtitle, body, footer), MAIN_QUICK)]


def _budget_rows(db: Session, user: User, start: datetime.date, end: datetime.date) -> list[dict]:
    rows = budget_status(db, user, start, end)
    if not rows:
        return []
    out: list[dict] = [{"type": "separator", "margin": "lg"}, _txt("預算", size="xs", color=MUTED, margin="md")]
    for r in rows:
        color, label = _status_of(r["ratio"])
        remain = f"剩 {money(r['remaining'])}" if r["remaining"] >= 0 else f"超 {money(-r['remaining'])}"
        out.append({"type": "box", "layout": "vertical", "contents": [
            {"type": "box", "layout": "horizontal", "contents": [
                _txt(f"{r['icon']} {r['name']}", size="sm", color=INK, flex=4),
                _txt(f"{label} {r['ratio']:.0%}", size="xs", color=INK_2, align="end", flex=4),
            ]},
            _bar(r["ratio"], color),
            _txt(f"{money(r['spent'])} / {money(r['budget'])}・{remain}", size="xs", color=MUTED, margin="xs"),
        ]})
    return out


def recent_message(db: Session, user: User) -> list[dict]:
    txns = (db.query(Transaction).filter(Transaction.user_id == user.id)
            .order_by(Transaction.occurred_on.desc(), Transaction.id.desc()).limit(10).all())
    if not txns:
        return [L.text("還沒有任何紀錄喔！傳「午餐 120」就能記第一筆。", MAIN_QUICK)]
    lines = ["🧾 最近 10 筆"]
    quick = []
    for t in txns:
        sign = "-" if t.kind == EXPENSE else "+"
        lines.append(f"{t.occurred_on.strftime('%m/%d')} {t.category.icon}{t.note or t.category.name} {sign}{money(t.amount)}")
        if len(quick) < 10:
            quick.append(L.qr_postback(f"🗑{(t.note or t.category.name)[:8]} {t.amount}",
                                       urlencode({"act": "del", "t": t.id}), f"刪除 {t.note or t.category.name} {t.amount}"))
    lines.append("\n點下方按鈕可以刪除該筆；要編輯請到「網頁」。")
    return [L.text("\n".join(lines), quick)]


def budget_command(db: Session, user: User, args: list[str]) -> list[dict]:
    start, end = period_bounds(user, period_key(user, today()))
    if not args:
        rows = _budget_rows(db, user, start, end)
        if not rows:
            return [L.text("還沒設定預算。\n傳「預算 20000」設定每月總預算，\n或「預算 餐飲 6000」設定分類預算。", MAIN_QUICK)]
        return [L.flex("預算使用狀況", _bubble("💰 本期預算", f"{start:%m/%d} – {end - datetime.timedelta(days=1):%m/%d}",
                                                rows[1:]), MAIN_QUICK)]
    amount_text = args[-1].replace(",", "")
    if not amount_text.isdigit():
        return [L.text("格式：「預算 20000」或「預算 餐飲 6000」（金額 0 代表取消）")]
    amount = int(amount_text)
    if len(args) == 1:
        set_budget(db, user, None, amount)
        label = "總預算"
    else:
        name = " ".join(args[:-1]).lstrip("#")
        cat = next((c for c in active_categories(db, user, EXPENSE) if c.name == name), None)
        if not cat:
            names = "、".join(c.name for c in active_categories(db, user, EXPENSE))
            return [L.text(f"找不到支出分類「{name}」。\n可用的分類：{names}")]
        set_budget(db, user, cat.id, amount)
        label = f"「{cat.name}」預算"
    db.flush()
    if amount <= 0:
        return [L.text(f"已取消{label}。", MAIN_QUICK)]
    used = spent(db, user, start, end, None if len(args) == 1 else cat.id)
    return [L.text(f"已設定每月{label} {money(amount)}。\n本期已花 {money(used)}（{used / amount:.0%}）。", MAIN_QUICK)]


def categories_message(db: Session, user: User) -> list[dict]:
    exp = "、".join(f"{c.icon}{c.name}" for c in active_categories(db, user, EXPENSE))
    inc = "、".join(f"{c.icon}{c.name}" for c in active_categories(db, user, INCOME))
    return [L.text(f"支出分類：\n{exp}\n\n收入分類：\n{inc}\n\n系統會依內容自動分類，也可以在最後加「#分類名」指定。"
                   "\n要新增分類或調整關鍵字，請到「網頁」→ 分類。", MAIN_QUICK)]


def reminder_command(db: Session, user: User, args: list[str]) -> list[dict]:
    arg = args[0] if args else ""
    if arg in ("關", "關閉", "off", "停"):
        user.reminder_enabled = False
        return [L.text("已關閉每日記帳提醒。")]
    if arg.isdigit() and 0 <= int(arg) <= 23:
        user.reminder_hour = int(arg)
        user.reminder_enabled = True
    elif arg in ("開", "開啟", "on", ""):
        user.reminder_enabled = True
    else:
        return [L.text("格式：「提醒 開」「提醒 關」或「提醒 21」（每天 21 點）")]
    return [L.text(f"⏰ 好的！每天 {user.reminder_hour}:00 如果當天還沒記帳，我會提醒你。")]


def undo(db: Session, user: User, ids: list[int] | None = None) -> list[dict]:
    q = db.query(Transaction).filter(Transaction.user_id == user.id)
    if ids:
        txns = q.filter(Transaction.id.in_(ids)).all()
    else:
        last = q.filter(Transaction.source == "line").order_by(Transaction.id.desc()).first()
        txns = [last] if last else []
    if not txns:
        return [L.text("沒有可以復原的紀錄（可能已經刪除了）。")]
    desc = "、".join(f"{t.note or t.category.name} {money(t.amount)}" for t in txns)
    for t in txns:
        db.delete(t)
    return [L.text(f"↩️ 已刪除：{desc}", MAIN_QUICK)]


def web_message(db: Session, user: User) -> list[dict]:
    link = create_login_link(db, user)
    bubble = _bubble("🌐 網頁版", "連結 10 分鐘內有效，只能使用一次", [
        _txt("在網頁可以看圖表、編輯每一筆、管理分類與預算、匯出 CSV。", size="sm", color=INK_2),
    ], [{"type": "button", "style": "primary", "color": SERIES, "action": {"type": "uri", "label": "開啟記帳本", "uri": link}}])
    return [L.flex("開啟網頁版記帳本", bubble)]


def run_command(db: Session, user: User, cmd: Command) -> list[dict]:
    day = today()
    if cmd.name == "help":
        return [L.text(HELP_TEXT, MAIN_QUICK)]
    if cmd.name == "today":
        return summary_message(db, user, "📅 今天", day, day + datetime.timedelta(days=1))
    if cmd.name == "yesterday":
        y = day - datetime.timedelta(days=1)
        return summary_message(db, user, "📅 昨天", y, day)
    if cmd.name == "week":
        return summary_message(db, user, "🗓️ 本週", *week_bounds(day))
    if cmd.name in ("month", "last_month"):
        key = period_key(user, day)
        if cmd.name == "last_month":
            key = shift_key(key, -1)
        start, end = period_bounds(user, key)
        title = f"📊 {'本月' if cmd.name == 'month' else '上月'}（{int(key[5:])} 月）"
        return summary_message(db, user, title, start, end, with_budget=True)
    if cmd.name == "recent":
        return recent_message(db, user)
    if cmd.name == "budget":
        return budget_command(db, user, cmd.args)
    if cmd.name == "undo":
        return undo(db, user)
    if cmd.name == "categories":
        return categories_message(db, user)
    if cmd.name == "web":
        return web_message(db, user)
    if cmd.name == "reminder":
        return reminder_command(db, user, cmd.args)
    return [L.text(HELP_TEXT)]


# ---------- 事件入口 ----------

def handle_text(db: Session, user: User, text: str) -> list[dict]:
    result = parse_message(text, today())
    if result.command:
        return run_command(db, user, result.command)
    if not result.entries:
        hint = result.errors[0] if len(result.errors) == 1 else "看不懂這則訊息"
        return [L.text(f"🤔 {hint}\n記帳請傳「內容 金額」，例如「午餐 120」。\n傳「說明」看所有用法。", MAIN_QUICK)]
    txns = [add_entry(db, user, e, "line") for e in result.entries]
    return recorded_message(db, user, txns, result.errors)


def handle_postback(db: Session, user: User, data: str) -> list[dict]:
    params = {k: v[0] for k, v in parse_qs(data).items()}
    act = params.get("act")

    def own_txn() -> Transaction | None:
        tid = params.get("t", "")
        t = db.get(Transaction, int(tid)) if tid.isdigit() else None
        return t if t and t.user_id == user.id else None

    if act == "undo":
        ids = [int(x) for x in params.get("ids", "").split(",") if x.isdigit()]
        return undo(db, user, ids) if ids else [L.text("沒有可以復原的紀錄。")]
    if act == "del":
        t = own_txn()
        return undo(db, user, [t.id]) if t else [L.text("這筆紀錄已經不存在了。")]
    if act == "cat":
        t = own_txn()
        cid = params.get("c", "")
        cat = db.get(Category, int(cid)) if cid.isdigit() else None
        if not t or not cat or cat.user_id != user.id:
            return [L.text("這筆紀錄已經不存在了。")]
        t.kind = cat.kind
        t.category_id = cat.id
        db.flush()
        db.refresh(t)
        return recorded_message(db, user, [t], [])
    if act == "flip":
        t = own_txn()
        if not t:
            return [L.text("這筆紀錄已經不存在了。")]
        t.kind = INCOME if t.kind == EXPENSE else EXPENSE
        t.category_id = find_category(db, user, t.kind, t.note).id
        db.flush()
        db.refresh(t)
        return recorded_message(db, user, [t], [])
    return []


def welcome_message(user: User) -> list[dict]:
    name = user.display_name or "你"
    login = get_settings().base_url.rstrip("/")
    return [L.text(
        f"嗨 {name}！我是 LINE 記帳本 📒\n\n直接傳「午餐 120」就能記一筆，"
        f"傳「本月」看統計，傳「說明」看所有用法。\n\n網頁版：{login}",
        MAIN_QUICK,
    )]
