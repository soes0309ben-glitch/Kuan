"""組隊挑戰：隊長開隊、分享邀請連結，最多 3 位登入的使用者答同一組題目，全員完成後公布隊內排名。"""

import random
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import catalog
from app.db import get_db
from app.dependencies import require_json, require_user
from app.models import DIFFICULTIES, Profile, Question, Team, TeamAnswer, TeamMember, User
from app.routers.profile import profile_dict

router = APIRouter(prefix="/api/teams")

MAX_MEMBERS = 3
VALID_CATEGORIES = set(catalog.CATEGORIES) | {catalog.MIXED}


def _team(db: Session, code: str) -> Team:
    team = db.scalar(select(Team).where(Team.code == code))
    if not team:
        raise HTTPException(404, "找不到這個隊伍，請確認邀請連結")
    return team


def _member(team: Team, user: User) -> TeamMember | None:
    return next((m for m in team.members if m.user_id == user.id), None)


def _require_member(team: Team, user: User) -> TeamMember:
    member = _member(team, user)
    if not member:
        raise HTTPException(403, "你還不是這個隊伍的成員，請先加入")
    return member


def _public_member(db: Session, m: TeamMember, *, show_score: bool, viewer_is_member: bool) -> dict:
    profile = profile_dict(m.user, db.get(Profile, m.user_id))
    if profile["avatar_type"] == "upload":
        if viewer_is_member:
            profile["avatar_url"] = f"/api/teams/avatar/{m.user_id}?v={profile['avatar_url'].split('v=')[-1]}"
        else:
            # 上傳的頭像只給隊友看；還沒加入的人看 Google 大頭貼
            profile["avatar_type"], profile["avatar_url"] = "google", m.user.picture or ""
    return {
        "user_id": m.user_id,
        "name": profile["nickname"] or m.user.name or m.user.email.split("@")[0],
        "profile": profile,
        "answered": len(m.answers),
        "finished": m.finished_at is not None,
        "score": m.score if show_score else None,
    }


def team_view(db: Session, team: Team, user: User) -> dict:
    all_done = len(team.members) > 0 and all(m.finished_at for m in team.members)
    me = _member(team, user)
    members = [
        # 自己的分數隨時看得到；別人的分數等全員完成才公布，避免邊看邊答
        _public_member(db, m, show_score=all_done or m.user_id == user.id, viewer_is_member=me is not None)
        for m in team.members
    ]
    data = {
        "code": team.code,
        "category": team.category,
        "difficulty": team.difficulty,
        "total": len(team.question_ids),
        "is_owner": team.owner_id == user.id,
        "is_member": me is not None,
        "max_members": MAX_MEMBERS,
        "members": members,
        "all_finished": all_done,
        "me": user.id,
        "my_answered": len(me.answers) if me else 0,
        "my_finished": bool(me and me.finished_at),
    }
    if all_done:
        ranked = sorted(members, key=lambda x: -x["score"])
        data["ranking"] = [{"user_id": m["user_id"], "name": m["name"], "score": m["score"]} for m in ranked]
        questions = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(team.question_ids)))}
        by_member = {m.user_id: {a.question_id: a for a in m.answers} for m in team.members}
        data["breakdown"] = [
            {
                "q": questions[qid].q,
                "emoji": questions[qid].emoji,
                "answer": catalog.correct_answer_text(questions[qid]) if questions[qid].type != "qa" else "（問答題，自評）",
                "scores": {uid: (ans[qid].score if qid in ans else None) for uid, ans in by_member.items()},
            }
            for qid in team.question_ids
            if qid in questions
        ]
    return data


class CreateBody(BaseModel):
    category: str
    difficulty: str


@router.post("", dependencies=[Depends(require_json)])
def create_team(body: CreateBody, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if body.category not in VALID_CATEGORIES or body.difficulty not in DIFFICULTIES:
        raise HTTPException(400, "主題或難度不正確")
    ids = catalog.pick_questions(db, body.category, body.difficulty)
    if not ids:
        raise HTTPException(404, "這個主題與難度目前還沒有題目")
    team = Team(code=secrets.token_urlsafe(8), owner_id=user.id, category=body.category,
                difficulty=body.difficulty, question_ids=ids)
    team.members.append(TeamMember(user_id=user.id))
    db.add(team)
    db.commit()
    return {"code": team.code}


@router.get("/mine")
def my_teams(user: User = Depends(require_user), db: Session = Depends(get_db)):
    memberships = db.scalars(
        select(TeamMember).where(TeamMember.user_id == user.id).order_by(TeamMember.joined_at.desc()).limit(20)
    )
    return {"teams": [team_view(db, m.team, user) for m in memberships]}


@router.get("/{code}")
def get_team(code: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return team_view(db, _team(db, code), user)


@router.post("/{code}/join", dependencies=[Depends(require_json)])
def join_team(code: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    team = _team(db, code)
    if _member(team, user):
        return team_view(db, team, user)
    if len(team.members) >= MAX_MEMBERS:
        raise HTTPException(409, f"這個隊伍已經滿 {MAX_MEMBERS} 人了")
    team.members.append(TeamMember(user_id=user.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    db.refresh(team)
    if len(team.members) > MAX_MEMBERS:
        # 兩人同時加入搶最後一個位置：後加入的退出
        db.delete(_member(team, user))
        db.commit()
        raise HTTPException(409, f"這個隊伍已經滿 {MAX_MEMBERS} 人了")
    return team_view(db, team, user)


def _answer_result(q: Question, ans: TeamAnswer) -> dict:
    return {
        "question_id": q.id,
        "given": ans.given,
        "score": ans.score,
        "correct_answer": catalog.correct_answer_text(q),
        "explain": q.explain,
        "ref": q.ref if q.type == "qa" else None,
    }


@router.get("/{code}/play")
def play(code: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """回傳和個人挑戰相同格式的題目資料，前端可以共用作答畫面。"""
    team = _team(db, code)
    member = _require_member(team, user)
    questions = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(team.question_ids)))}
    answers = {a.question_id: a for a in member.answers}
    rng = random.Random(f"team-{team.id}")  # 同一隊每個人看到的選項順序一樣
    return {
        "id": team.code,
        "category": team.category,
        "difficulty": team.difficulty,
        "score": member.score,
        "total": len(team.question_ids),
        "answered": len(answers),
        "finished": member.finished_at is not None,
        "questions": [catalog.public_question(questions[qid], rng) for qid in team.question_ids if qid in questions],
        "results": {qid: _answer_result(questions[qid], a) for qid, a in answers.items() if qid in questions},
    }


def _maybe_finish(team: Team, member: TeamMember) -> None:
    if len(member.answers) >= len(team.question_ids) and all(a.score is not None for a in member.answers):
        member.score = sum(a.score for a in member.answers)
        member.finished_at = datetime.now(timezone.utc)


class AnswerBody(BaseModel):
    question_id: int
    given: str = ""


@router.post("/{code}/answer", dependencies=[Depends(require_json)])
def answer(code: str, body: AnswerBody, user: User = Depends(require_user), db: Session = Depends(get_db)):
    team = _team(db, code)
    member = _require_member(team, user)
    if body.question_id not in team.question_ids:
        raise HTTPException(400, "這題不在這個隊伍的題目裡")
    if any(a.question_id == body.question_id for a in member.answers):
        raise HTTPException(409, "這題已經作答過了")
    q = db.get(Question, body.question_id)
    given = body.given.strip()[:2000]
    ans = TeamAnswer(member=member, question_id=q.id, given=given, score=catalog.grade(q, given))
    db.add(ans)
    _maybe_finish(team, member)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "這題已經作答過了")
    return {**_answer_result(q, ans), "finished": member.finished_at is not None}


class SelfGradeBody(BaseModel):
    question_id: int
    score: float


@router.post("/{code}/self-grade", dependencies=[Depends(require_json)])
def self_grade(code: str, body: SelfGradeBody, user: User = Depends(require_user), db: Session = Depends(get_db)):
    team = _team(db, code)
    member = _require_member(team, user)
    if body.score not in (0, 0.5, 1):
        raise HTTPException(400, "自評分數只能是 0、0.5 或 1")
    ans = next((a for a in member.answers if a.question_id == body.question_id), None)
    if not ans or db.get(Question, body.question_id).type != "qa":
        raise HTTPException(400, "只有已作答的問答題可以自評")
    if ans.score is not None:
        raise HTTPException(409, "這題已經自評過了")
    ans.score = body.score
    _maybe_finish(team, member)
    db.commit()
    return {"ok": True, "finished": member.finished_at is not None, "score": member.score}


@router.get("/avatar/{user_id}")
def teammate_avatar(user_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """隊友上傳的頭像：只有同隊的人（或本人）看得到。"""
    shared = user_id == user.id or db.scalar(
        select(TeamMember.id)
        .where(TeamMember.user_id == user_id)
        .where(TeamMember.team_id.in_(select(TeamMember.team_id).where(TeamMember.user_id == user.id)))
        .limit(1)
    )
    profile = db.get(Profile, user_id)
    if not shared or not profile or not profile.avatar_data:
        raise HTTPException(404)
    return Response(profile.avatar_data, media_type=profile.avatar_mime,
                    headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})
