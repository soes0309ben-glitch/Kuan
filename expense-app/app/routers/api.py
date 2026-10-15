"""網頁版用的 JSON API（需登入）。"""

import csv
import datetime
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.categories import active_categories, fallback_category
from app.config import get_settings
from app.db import get_db
from app.dependencies import get_current_user, require_json, require_user
from app.ledger import (
    budget_status,
    period_bounds,
    period_key,
    serialize_txn,
    set_budget,
    shift_key,
    summarize,
    today,
)
from app.models import EXPENSE, INCOME, Budget, Category, Transaction, User
from app.parser import MAX_AMOUNT

router = APIRouter(prefix="/api")
JSON = [Depends(require_json)]
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _month(user: User, month: str | None) -> str:
    if month is None:
        return period_key(user, today())
    if not _MONTH.match(month):
        raise HTTPException(422, "月份格式應為 YYYY-MM")
    return month


def _own_category(db: Session, user: User, category_id: int) -> Category:
    cat = db.get(Category, category_id)
    if not cat or cat.user_id != user.id:
        raise HTTPException(404, "找不到這個分類")
    return cat


def _own_txn(db: Session, user: User, txn_id: int) -> Transaction:
    t = db.get(Transaction, txn_id)
    if not t or t.user_id != user.id:
        raise HTTPException(404, "找不到這筆紀錄")
    return t


def serialize_category(c: Category) -> dict:
    return {"id": c.id, "kind": c.kind, "name": c.name, "icon": c.icon, "keywords": c.keyword_list,
            "sort_order": c.sort_order}


# ---------- 設定與個人資料 ----------

@router.get("/config")
def config():
    s = get_settings()
    return {"app_name": s.app_name, "line_login": s.line_login_enabled, "dev_login": s.dev_login,
            "add_friend_url": s.line_bot_add_friend_url}


@router.get("/me")
def me(user: User | None = Depends(get_current_user)):
    if not user:
        return {"user": None}
    return {"user": {
        "id": user.id, "name": user.display_name, "picture": user.picture_url, "bot_friend": user.bot_friend,
        "reminder_enabled": user.reminder_enabled, "reminder_hour": user.reminder_hour,
        "month_start_day": user.month_start_day, "current_month": period_key(user, today()),
        "today": today().isoformat(),
    }}


class SettingsIn(BaseModel):
    reminder_enabled: bool | None = None
    reminder_hour: int | None = Field(None, ge=0, le=23)
    month_start_day: int | None = Field(None, ge=1, le=28)


@router.post("/me/settings", dependencies=JSON)
def update_settings(body: SettingsIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(user, key, value)
    db.commit()
    return {"ok": True}


# ---------- 分類 ----------

class CategoryIn(BaseModel):
    kind: str = EXPENSE
    name: str = Field(min_length=1, max_length=30)
    icon: str = Field("", max_length=16)
    keywords: list[str] = []

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in (EXPENSE, INCOME):
            raise ValueError("kind 必須是 expense 或 income")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip().lstrip("#")
        if not v:
            raise ValueError("請輸入分類名稱")
        return v

    def keywords_text(self) -> str:
        words = [w.strip().replace(",", "") for w in self.keywords if w.strip()]
        return ",".join(dict.fromkeys(words))[:1000]


@router.get("/categories")
def list_categories(user: User = Depends(require_user), db: Session = Depends(get_db)):
    return {"categories": [serialize_category(c) for c in active_categories(db, user)]}


@router.post("/categories", dependencies=JSON)
def create_category(body: CategoryIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    existing = db.query(Category).filter(Category.user_id == user.id, Category.kind == body.kind,
                                         Category.name == body.name).first()
    if existing and not existing.archived:
        raise HTTPException(409, "已經有同名的分類")
    order = len(active_categories(db, user, body.kind))
    cat = existing or Category(user_id=user.id, kind=body.kind, name=body.name)
    cat.archived = False
    cat.icon, cat.keywords, cat.sort_order = body.icon, body.keywords_text(), order
    db.add(cat)
    db.commit()
    return serialize_category(cat)


@router.put("/categories/{category_id}", dependencies=JSON)
def update_category(category_id: int, body: CategoryIn, user: User = Depends(require_user),
                    db: Session = Depends(get_db)):
    cat = _own_category(db, user, category_id)
    clash = db.query(Category).filter(Category.user_id == user.id, Category.kind == cat.kind,
                                      Category.name == body.name, Category.id != cat.id).first()
    if clash:
        raise HTTPException(409, "已經有同名的分類")
    cat.name, cat.icon, cat.keywords = body.name, body.icon, body.keywords_text()
    db.commit()
    return serialize_category(cat)


@router.delete("/categories/{category_id}")
def delete_category(category_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """封存分類（舊紀錄保留），並把它的預算刪除。"""
    cat = _own_category(db, user, category_id)
    if len(active_categories(db, user, cat.kind)) <= 1:
        raise HTTPException(409, "至少要保留一個分類")
    cat.archived = True
    db.query(Budget).filter(Budget.user_id == user.id, Budget.category_id == cat.id).delete()
    db.commit()
    return {"ok": True}


class ReorderIn(BaseModel):
    ids: list[int]


@router.post("/categories/reorder", dependencies=JSON)
def reorder_categories(body: ReorderIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    for order, cid in enumerate(body.ids):
        _own_category(db, user, cid).sort_order = order
    db.commit()
    return {"ok": True}


# ---------- 收支紀錄 ----------

class TransactionIn(BaseModel):
    kind: str = EXPENSE
    amount: int = Field(gt=0, le=MAX_AMOUNT)
    category_id: int | None = None
    note: str = Field("", max_length=200)
    date: datetime.date | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in (EXPENSE, INCOME):
            raise ValueError("kind 必須是 expense 或 income")
        return v


def _apply(db: Session, user: User, t: Transaction, body: TransactionIn) -> None:
    if body.category_id is not None:
        cat = _own_category(db, user, body.category_id)
        if cat.kind != body.kind:
            raise HTTPException(422, "分類和收支類型不一致")
    else:
        cat = fallback_category(db, user, body.kind)
    t.kind, t.amount, t.category_id = body.kind, body.amount, cat.id
    t.note = body.note.strip()
    t.occurred_on = body.date or today()


@router.get("/transactions")
def list_transactions(
    month: str | None = None,
    kind: str | None = None,
    category_id: int | None = None,
    q: str | None = Query(None, max_length=50),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    key = _month(user, month)
    start, end = period_bounds(user, key)
    query = db.query(Transaction).filter(Transaction.user_id == user.id, Transaction.occurred_on >= start,
                                         Transaction.occurred_on < end)
    if kind in (EXPENSE, INCOME):
        query = query.filter(Transaction.kind == kind)
    if category_id:
        query = query.filter(Transaction.category_id == category_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.join(Category, Category.id == Transaction.category_id).filter(
            or_(Transaction.note.ilike(like), Category.name.ilike(like)))
    rows = query.order_by(Transaction.occurred_on.desc(), Transaction.id.desc()).all()
    return {"month": key, "start": start.isoformat(), "end": (end - datetime.timedelta(days=1)).isoformat(),
            "transactions": [serialize_txn(t) for t in rows]}


@router.post("/transactions", dependencies=JSON)
def create_transaction(body: TransactionIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    t = Transaction(user_id=user.id, source="web")
    _apply(db, user, t, body)
    db.add(t)
    db.commit()
    db.refresh(t)
    return serialize_txn(t)


@router.put("/transactions/{txn_id}", dependencies=JSON)
def update_transaction(txn_id: int, body: TransactionIn, user: User = Depends(require_user),
                       db: Session = Depends(get_db)):
    t = _own_txn(db, user, txn_id)
    _apply(db, user, t, body)
    db.commit()
    db.refresh(t)
    return serialize_txn(t)


@router.delete("/transactions/{txn_id}")
def delete_transaction(txn_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    db.delete(_own_txn(db, user, txn_id))
    db.commit()
    return {"ok": True}


# ---------- 統計 ----------

@router.get("/summary")
def summary(month: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    key = _month(user, month)
    start, end = period_bounds(user, key)
    data = summarize(db, user, start, end)
    prev_start, prev_end = period_bounds(user, shift_key(key, -1))
    prev = summarize(db, user, prev_start, prev_end)
    data.update({
        "month": key,
        "previous": {"month": shift_key(key, -1), "expense": prev["expense"], "income": prev["income"]},
        "budgets": budget_status(db, user, start, end),
    })
    # 本期進行中時，算出日均與預估整期支出
    day = today()
    if start <= day < end:
        elapsed = (day - start).days + 1
        total_days = (end - start).days
        data["daily_average"] = round(data["expense"] / elapsed)
        data["projected_expense"] = round(data["expense"] / elapsed * total_days)
    else:
        data["daily_average"] = round(data["expense"] / max((end - start).days, 1))
        data["projected_expense"] = None
    return data


@router.get("/trend")
def trend(months: int = Query(6, ge=2, le=24), user: User = Depends(require_user), db: Session = Depends(get_db)):
    current = period_key(user, today())
    out = []
    for i in range(months - 1, -1, -1):
        key = shift_key(current, -i)
        s = summarize(db, user, *period_bounds(user, key))
        out.append({"month": key, "expense": s["expense"], "income": s["income"]})
    return {"months": out}


# ---------- 預算 ----------

class BudgetIn(BaseModel):
    category_id: int | None = None
    amount: int = Field(ge=0, le=MAX_AMOUNT)


@router.get("/budgets")
def list_budgets(month: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    start, end = period_bounds(user, _month(user, month))
    return {"budgets": budget_status(db, user, start, end)}


@router.post("/budgets", dependencies=JSON)
def upsert_budget(body: BudgetIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """設定預算；amount 為 0 代表刪除。"""
    if body.category_id is not None and _own_category(db, user, body.category_id).kind != EXPENSE:
        raise HTTPException(422, "只有支出分類可以設定預算")
    set_budget(db, user, body.category_id, body.amount)
    db.commit()
    return {"ok": True}


# ---------- 匯出 ----------

def _csv_safe(value: str) -> str:
    # 防 CSV 公式注入：開頭是 = + - @ 的儲存格前面加 '
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


@router.get("/export.csv")
def export_csv(month: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """匯出 CSV；不帶 month 就匯出全部。開頭加 BOM，Excel 打開中文才不會亂碼。"""
    query = db.query(Transaction).filter(Transaction.user_id == user.id)
    filename = "expenses-all.csv"
    if month:
        start, end = period_bounds(user, _month(user, month))
        query = query.filter(Transaction.occurred_on >= start, Transaction.occurred_on < end)
        filename = f"expenses-{month}.csv"
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["日期", "收支", "分類", "金額", "備註", "來源"])
    for t in query.order_by(Transaction.occurred_on, Transaction.id):
        writer.writerow([t.occurred_on.isoformat(), "支出" if t.kind == EXPENSE else "收入",
                         _csv_safe(t.category.name), t.amount, _csv_safe(t.note), "LINE" if t.source == "line" else "網頁"])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
