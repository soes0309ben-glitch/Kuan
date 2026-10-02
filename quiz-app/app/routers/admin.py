"""管理者：匯入題庫、查看統計、重設某人的挑戰。權限由 ADMIN_EMAILS 控制。"""

import secrets

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import catalog
from app.config import get_settings
from app.db import get_db
from app.dependencies import require_admin, require_json
from app.models import Attempt, Question, User

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])
# 不需登入、改用匯入密碼驗證的入口（IMPORT_TOKEN 沒設定時一律拒絕）
token_router = APIRouter(prefix="/api/admin")


def _import(db: Session, items: list[dict]) -> dict:
    try:
        return catalog.import_questions(db, items)
    except catalog.ImportError_ as e:
        db.rollback()
        raise HTTPException(400, str(e))


@router.post("/import", dependencies=[Depends(require_json)])
def import_bank(items: list[dict] = Body(...), db: Session = Depends(get_db)):
    return _import(db, items)


@token_router.post("/import-with-token", dependencies=[Depends(require_json)])
def import_bank_with_token(
    items: list[dict] = Body(...),
    x_import_token: str = Header(""),
    db: Session = Depends(get_db),
):
    expected = get_settings().import_token.strip()
    # 太短的密碼視同未設定，避免被猜中
    if len(expected) < 32 or not secrets.compare_digest(x_import_token.strip(), expected):
        raise HTTPException(403, "匯入密碼不正確或未啟用")
    return _import(db, items)


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    return {
        "questions": db.scalar(select(func.count(Question.id))),
        "users": db.scalar(select(func.count(User.id))),
        "subscribers": db.scalar(select(func.count(User.id)).where(User.subscription_status.in_(("active", "trialing")))),
        "attempts": db.scalar(select(func.count(Attempt.id))),
        "finished_attempts": db.scalar(select(func.count(Attempt.id)).where(Attempt.finished_at.is_not(None))),
    }


class ResetBody(BaseModel):
    email: str
    category: str
    difficulty: str


@router.post("/reset-attempt", dependencies=[Depends(require_json)])
def reset_attempt(body: ResetBody, db: Session = Depends(get_db)):
    attempt = db.scalar(
        select(Attempt)
        .join(User)
        .where(
            func.lower(User.email) == body.email.strip().lower(),
            Attempt.category == body.category,
            Attempt.difficulty == body.difficulty,
        )
    )
    if not attempt:
        raise HTTPException(404, "找不到這筆挑戰紀錄")
    db.delete(attempt)
    db.commit()
    return {"ok": True}
