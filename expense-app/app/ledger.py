"""記帳的商業邏輯：新增、統計、預算。LINE 機器人與網頁 API 共用。"""

import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.categories import active_categories, best_match, find_category
from app.config import get_settings
from app.models import EXPENSE, INCOME, Budget, Category, Transaction, User
from app.parser import Entry

# 預算用到這些比例時提醒一次（跨過門檻那一筆才提醒，不會每筆都講）
BUDGET_THRESHOLDS = (0.8, 1.0)


def today() -> datetime.date:
    return datetime.datetime.now(get_settings().tz).date()


# ---------- 期間 ----------

def period_bounds(user: User, key: str) -> tuple[datetime.date, datetime.date]:
    """「YYYY-MM」對應的期間 [start, end)。月結日為 d 時，期間是當月 d 日到下個月 d-1 日。"""
    year, month = (int(x) for x in key.split("-"))
    start_day = min(max(user.month_start_day or 1, 1), 28)
    start = datetime.date(year, month, start_day)
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    return start, datetime.date(ny, nm, start_day)


def period_key(user: User, day: datetime.date) -> str:
    start_day = min(max(user.month_start_day or 1, 1), 28)
    y, m = day.year, day.month
    if day.day < start_day:
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"{y:04d}-{m:02d}"


def shift_key(key: str, months: int) -> str:
    y, m = (int(x) for x in key.split("-"))
    idx = y * 12 + (m - 1) + months
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def week_bounds(day: datetime.date) -> tuple[datetime.date, datetime.date]:
    start = day - datetime.timedelta(days=day.weekday())
    return start, start + datetime.timedelta(days=7)


# ---------- 新增 ----------

def _guess_kind(db: Session, user: User, entry: Entry) -> str:
    """沒標 +/收入 時判斷收支：#分類 優先；否則收入關鍵字命中得比支出長才算收入（「薪水 50000」）。"""
    expense_cats, income_cats = active_categories(db, user, EXPENSE), active_categories(db, user, INCOME)
    if entry.category_hint:
        for c in [*expense_cats, *income_cats]:
            if c.name == entry.category_hint:
                return c.kind
    _, income_len = best_match(income_cats, entry.note)
    _, expense_len = best_match(expense_cats, entry.note)
    return INCOME if income_len > expense_len else EXPENSE


def add_entry(db: Session, user: User, entry: Entry, source: str) -> Transaction:
    kind = entry.kind or _guess_kind(db, user, entry)
    category = find_category(db, user, kind, entry.note, entry.category_hint)
    txn = Transaction(
        user_id=user.id, kind=kind, amount=entry.amount, category_id=category.id,
        note=entry.note, occurred_on=entry.occurred_on, source=source,
    )
    db.add(txn)
    db.flush()
    return txn


# ---------- 統計 ----------

def summarize(db: Session, user: User, start: datetime.date, end: datetime.date) -> dict:
    base = db.query(Transaction).filter(
        Transaction.user_id == user.id, Transaction.occurred_on >= start, Transaction.occurred_on < end
    )
    totals = {EXPENSE: 0, INCOME: 0}
    count = 0
    for kind, total, n in base.with_entities(Transaction.kind, func.sum(Transaction.amount), func.count()).group_by(
        Transaction.kind
    ):
        totals[kind] = int(total or 0)
        count += n

    by_category = []
    rows = (
        base.join(Category, Category.id == Transaction.category_id)
        .with_entities(Category.id, Category.name, Category.icon, Category.kind,
                       func.sum(Transaction.amount), func.count())
        .group_by(Category.id, Category.name, Category.icon, Category.kind)
        .all()
    )
    for cid, name, icon, kind, total, n in rows:
        by_category.append({"id": cid, "name": name, "icon": icon, "kind": kind, "amount": int(total), "count": n})
    by_category.sort(key=lambda r: -r["amount"])

    daily_map: dict[datetime.date, dict] = {}
    for day, kind, total in base.with_entities(
        Transaction.occurred_on, Transaction.kind, func.sum(Transaction.amount)
    ).group_by(Transaction.occurred_on, Transaction.kind):
        daily_map.setdefault(day, {EXPENSE: 0, INCOME: 0})[kind] = int(total)
    daily = []
    d = start
    while d < end:
        v = daily_map.get(d, {EXPENSE: 0, INCOME: 0})
        daily.append({"date": d.isoformat(), "expense": v[EXPENSE], "income": v[INCOME]})
        d += datetime.timedelta(days=1)

    return {
        "start": start.isoformat(),
        "end": (end - datetime.timedelta(days=1)).isoformat(),
        "expense": totals[EXPENSE],
        "income": totals[INCOME],
        "balance": totals[INCOME] - totals[EXPENSE],
        "count": count,
        "by_category": by_category,
        "daily": daily,
    }


def spent(db: Session, user: User, start: datetime.date, end: datetime.date, category_id: int | None = None) -> int:
    q = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.user_id == user.id, Transaction.kind == EXPENSE,
        Transaction.occurred_on >= start, Transaction.occurred_on < end,
    )
    if category_id is not None:
        q = q.filter(Transaction.category_id == category_id)
    return int(q.scalar() or 0)


def budget_status(db: Session, user: User, start: datetime.date, end: datetime.date) -> list[dict]:
    """每個預算的使用狀況；總預算排第一。"""
    budgets = db.query(Budget).filter(Budget.user_id == user.id).all()
    cats = {c.id: c for c in db.query(Category).filter(Category.user_id == user.id)}
    out = []
    for b in budgets:
        cat = cats.get(b.category_id) if b.category_id else None
        if b.category_id and (not cat or cat.archived):
            continue
        used = spent(db, user, start, end, b.category_id)
        out.append({
            "category_id": b.category_id,
            "name": cat.name if cat else "總預算",
            "icon": cat.icon if cat else "💰",
            "budget": b.amount,
            "spent": used,
            "remaining": b.amount - used,
            "ratio": round(used / b.amount, 4) if b.amount else 0,
        })
    out.sort(key=lambda r: (r["category_id"] is not None, -r["ratio"]))
    return out


def budget_alerts(db: Session, user: User, txns: list[Transaction]) -> list[str]:
    """這次新增的支出讓哪些預算跨過 80% / 100%。"""
    expenses = [t for t in txns if t.kind == EXPENSE]
    if not expenses:
        return []
    alerts = []
    keys = {period_key(user, t.occurred_on) for t in expenses}
    for key in sorted(keys):
        start, end = period_bounds(user, key)
        in_period = [t for t in expenses if start <= t.occurred_on < end]
        for b in db.query(Budget).filter(Budget.user_id == user.id):
            relevant = [t for t in in_period if b.category_id in (None, t.category_id)]
            if not relevant or b.amount <= 0:
                continue
            after = spent(db, user, start, end, b.category_id)
            before = after - sum(t.amount for t in relevant)
            label = "總預算" if b.category_id is None else f"「{db.get(Category, b.category_id).name}」預算"
            for th in reversed(BUDGET_THRESHOLDS):
                if before < b.amount * th <= after:
                    if th >= 1:
                        alerts.append(f"🚨 {label}已超支 ${after - b.amount:,}（${after:,} / ${b.amount:,}）")
                    else:
                        alerts.append(f"⚠️ {label}已用 {after / b.amount:.0%}，剩 ${b.amount - after:,}")
                    break
    return alerts


def set_budget(db: Session, user: User, category_id: int | None, amount: int) -> None:
    existing = db.query(Budget).filter(Budget.user_id == user.id, Budget.category_id.is_(None) if category_id is None
                                       else Budget.category_id == category_id).first()
    if amount <= 0:
        if existing:
            db.delete(existing)
        return
    if existing:
        existing.amount = amount
    else:
        db.add(Budget(user_id=user.id, category_id=category_id, amount=amount))


def serialize_txn(t: Transaction) -> dict:
    return {
        "id": t.id,
        "kind": t.kind,
        "amount": t.amount,
        "category_id": t.category_id,
        "category": t.category.name if t.category else "",
        "icon": t.category.icon if t.category else "",
        "note": t.note,
        "date": t.occurred_on.isoformat(),
        "source": t.source,
    }
