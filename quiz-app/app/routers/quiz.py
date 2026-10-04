"""作答 API：每位使用者在每個「主題 × 難度」只有一次挑戰機會，判分全在伺服器。"""

import random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import catalog, pdf_export
from app.config import get_settings
from app.db import get_db
from app.dependencies import get_current_user, require_json, require_user
from app.models import DIFFICULTIES, Attempt, AttemptAnswer, Profile, Question, User
from app.routers.profile import profile_dict

router = APIRouter(prefix="/api")

IMAGE_DIR = Path(__file__).resolve().parent.parent / "static" / "images"
VALID_CATEGORIES = set(catalog.CATEGORIES) | {catalog.MIXED}


def attempt_summary(a: Attempt) -> dict:
    return {
        "id": a.id,
        "category": a.category,
        "difficulty": a.difficulty,
        "score": a.score,
        "total": len(a.question_ids),
        "answered": len(a.answers),
        "finished": a.finished_at is not None,
    }


@router.get("/config")
def config(db: Session = Depends(get_db)):
    counts = {f"{c}:{d}": n for c, d, n in db.execute(
        select(Question.cat, Question.difficulty, func.count()).group_by(Question.cat, Question.difficulty)
    )}
    return {
        "categories": catalog.CATEGORIES,
        "difficulties": list(DIFFICULTIES),
        "counts": counts,
        "total": sum(counts.values()),
        "per_attempt": catalog.QUESTIONS_PER_ATTEMPT,
        "per_attempt_mixed": catalog.MIXED_PER_ATTEMPT,
        "price_twd": get_settings().monthly_price_twd,
    }


@router.get("/me")
def me(user: User | None = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        return {"user": None}
    return {
        "profile": profile_dict(user, db.get(Profile, user.id)),
        "user": {
            "name": user.name,
            "email": user.email,
            "picture": user.picture,
            "subscribed": user.is_subscribed,
            "subscription_status": user.subscription_status,
            "period_end": user.subscription_period_end.isoformat() if user.subscription_period_end else None,
            "is_admin": user.email.lower() in get_settings().admin_email_set,
        },
        "attempts": [attempt_summary(a) for a in user.attempts],
    }


class StartBody(BaseModel):
    category: str
    difficulty: str


@router.post("/attempts", dependencies=[Depends(require_json)])
def start_attempt(body: StartBody, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if body.category not in VALID_CATEGORIES or body.difficulty not in DIFFICULTIES:
        raise HTTPException(400, "主題或難度不正確")
    existing = db.scalar(
        select(Attempt).where(
            Attempt.user_id == user.id, Attempt.category == body.category, Attempt.difficulty == body.difficulty
        )
    )
    if existing:
        if existing.finished_at:
            raise HTTPException(409, "這個主題與難度你已經挑戰過了，每人只能挑戰一次")
        return {"attempt_id": existing.id, "resumed": True}

    ids = catalog.pick_questions(db, body.category, body.difficulty)
    if not ids:
        raise HTTPException(404, "這個主題與難度目前還沒有題目")
    attempt = Attempt(user_id=user.id, category=body.category, difficulty=body.difficulty, question_ids=ids)
    db.add(attempt)
    try:
        db.commit()
    except IntegrityError:
        # 同時按兩次開始：以先建立的那一筆為準
        db.rollback()
        existing = db.scalar(
            select(Attempt).where(
                Attempt.user_id == user.id, Attempt.category == body.category, Attempt.difficulty == body.difficulty
            )
        )
        return {"attempt_id": existing.id, "resumed": True}
    return {"attempt_id": attempt.id, "resumed": False}


def _own_attempt(db: Session, attempt_id: int, user: User) -> Attempt:
    attempt = db.get(Attempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(404, "找不到這次挑戰")
    return attempt


def _answer_result(q: Question, ans: AttemptAnswer) -> dict:
    return {
        "question_id": q.id,
        "given": ans.given,
        "score": ans.score,
        "correct_answer": catalog.correct_answer_text(q),
        "explain": q.explain,
        "ref": q.ref if q.type == "qa" else None,
    }


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    attempt = _own_attempt(db, attempt_id, user)
    questions = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(attempt.question_ids)))}
    answers = {a.question_id: a for a in attempt.answers}
    # 同一次挑戰重新整理時選項順序固定，避免看起來像換題
    rng = random.Random(attempt.id)
    return {
        **attempt_summary(attempt),
        "questions": [catalog.public_question(questions[qid], rng) for qid in attempt.question_ids if qid in questions],
        "results": {qid: _answer_result(questions[qid], a) for qid, a in answers.items() if qid in questions},
    }


def _maybe_finish(attempt: Attempt) -> None:
    if len(attempt.answers) >= len(attempt.question_ids) and all(a.score is not None for a in attempt.answers):
        attempt.score = sum(a.score for a in attempt.answers)
        attempt.finished_at = datetime.now(timezone.utc)


class AnswerBody(BaseModel):
    question_id: int
    given: str = ""


@router.post("/attempts/{attempt_id}/answer", dependencies=[Depends(require_json)])
def answer(attempt_id: int, body: AnswerBody, user: User = Depends(require_user), db: Session = Depends(get_db)):
    attempt = _own_attempt(db, attempt_id, user)
    if body.question_id not in attempt.question_ids:
        raise HTTPException(400, "這題不在這次挑戰裡")
    if any(a.question_id == body.question_id for a in attempt.answers):
        raise HTTPException(409, "這題已經作答過了")
    q = db.get(Question, body.question_id)
    given = body.given.strip()[:2000]
    ans = AttemptAnswer(attempt=attempt, question_id=q.id, given=given, score=catalog.grade(q, given))
    db.add(ans)
    _maybe_finish(attempt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "這題已經作答過了")
    return {**_answer_result(q, ans), "finished": attempt.finished_at is not None}


class SelfGradeBody(BaseModel):
    question_id: int
    score: float


@router.post("/attempts/{attempt_id}/self-grade", dependencies=[Depends(require_json)])
def self_grade(attempt_id: int, body: SelfGradeBody, user: User = Depends(require_user), db: Session = Depends(get_db)):
    attempt = _own_attempt(db, attempt_id, user)
    if body.score not in (0, 0.5, 1):
        raise HTTPException(400, "自評分數只能是 0、0.5 或 1")
    ans = next((a for a in attempt.answers if a.question_id == body.question_id), None)
    q = db.get(Question, body.question_id)
    if not ans or q.type != "qa":
        raise HTTPException(400, "只有已作答的問答題可以自評")
    if ans.score is not None:
        raise HTTPException(409, "這題已經自評過了")
    ans.score = body.score
    _maybe_finish(attempt)
    db.commit()
    return {"ok": True, "finished": attempt.finished_at is not None, "score": attempt.score}


@router.get("/media/{question_id}")
def media(question_id: int, db: Session = Depends(get_db)):
    # 以題號取圖，前端看不到檔名（檔名常常就是答案）
    q = db.get(Question, question_id)
    if not q or not q.img:
        raise HTTPException(404)
    path = (IMAGE_DIR / q.img).resolve()
    if path.parent != IMAGE_DIR or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


def _bank_query(cat: str, difficulty: str, type: str, q: str):
    stmt = select(Question)
    if cat:
        stmt = stmt.where(Question.cat == cat)
    if difficulty:
        stmt = stmt.where(Question.difficulty == difficulty)
    if type:
        stmt = stmt.where(Question.type == type)
    if q:
        stmt = stmt.where(Question.q.contains(q))
    return stmt


def _answer_visible(user: User):
    """題庫總覽登入即可免費瀏覽；答案是付費內容。

    訂閱會員看得到全部答案；免費使用者只看得到自己已挑戰完的「主題 × 難度」（結果頁本來就會顯示）。
    """
    if user.is_subscribed:
        return lambda q: True
    played = {(a.category, a.difficulty) for a in user.attempts if a.finished_at}
    return lambda q: (q.cat, q.difficulty) in played


ORDER = (Question.cat, Question.difficulty, Question.id)


@router.get("/bank")
def bank(
    cat: str = "",
    difficulty: str = "",
    type: str = "",
    q: str = "",
    page: int = 1,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    stmt = _bank_query(cat, difficulty, type, q)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    page_size = 30
    rows = db.scalars(stmt.order_by(*ORDER).offset((max(page, 1) - 1) * page_size).limit(page_size))
    visible = _answer_visible(user)
    return {
        "total": total,
        "page": page,
        "pages": max(1, -(-total // page_size)),
        "subscribed": user.is_subscribed,
        "questions": [catalog.full_question(r, reveal=visible(r)) for r in rows],
    }


@router.get("/bank/export.pdf")
def export_pdf(
    cat: str = "",
    difficulty: str = "",
    type: str = "",
    q: str = "",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    # PDF 是訂閱會員專屬功能，內容一律附全部答案與解說
    if not user.is_subscribed:
        raise HTTPException(402, "匯出 PDF 需要訂閱會員，訂閱後即可下載含全部答案與解說的題本")
    rows = list(db.scalars(_bank_query(cat, difficulty, type, q).order_by(*ORDER)))
    labels = [
        catalog.CATEGORIES.get(cat, "全部主題"),
        pdf_export.DIFF_LABEL.get(difficulty, "全部難度"),
        pdf_export.TYPE_LABEL.get(type, "全部題型"),
    ] + ([f"關鍵字「{q}」"] if q else [])
    pdf = pdf_export.build_pdf(rows, owner=user.email, filters="・".join(labels))
    filename = quote(f"知識大挑戰題庫_{datetime.now().strftime('%Y%m%d')}.pdf")
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=quiz-bank.pdf; filename*=UTF-8''{filename}"},
    )
