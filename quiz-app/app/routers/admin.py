"""管理者：匯入題庫、查看統計、重設某人的挑戰。權限由 ADMIN_EMAILS 控制。"""

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import catalog
from app.db import get_db
from app.dependencies import require_admin, require_json
from app.models import Attempt, Question, User

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


@router.post("/import", dependencies=[Depends(require_json)])
def import_bank(items: list[dict] = Body(...), db: Session = Depends(get_db)):
    try:
        return catalog.import_questions(db, items)
    except catalog.ImportError_ as e:
        db.rollback()
        raise HTTPException(400, str(e))


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
