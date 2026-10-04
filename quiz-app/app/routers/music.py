"""音樂品味：猜歌手、猜年代、猜歌名、emoji 猜歌、動漫歌，以及紅藍兩隊（3v3～5v5）同步搶答對戰。

題庫在 app/music_bank.json（只有歌名、歌手、年份等事實資料，不含歌詞、錄音或 MV）。
對戰不用 WebSocket：前端每秒輪詢房間狀態，伺服器依「開始時間＋經過秒數」算出現在第幾題。
"""

import json
import random
import secrets
import time
import urllib.parse
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.billing import music_subscribed
from app.dependencies import require_json, require_user
from app.models import MusicAnswer, MusicPlayer, MusicRoom, Profile, User
from app.routers.profile import profile_dict

router = APIRouter(prefix="/api/music")

MODES = {"mix": "⚡ 綜合", "emoji": "😀 emoji 猜歌", "singer": "🎤 猜歌手", "year": "📅 猜年代", "title": "🎵 猜歌名", "anime": "🎌 動漫歌"}
REGIONS = {"all": "全部", "west": "西洋", "jp": "日語", "zh": "華語", "kr": "韓語"}
TEAM_SIZES = (3, 4, 5)
ROUND_QUESTIONS = 10
ANSWER_SECONDS = 15  # 每題作答時間
REVEAL_SECONDS = 3  # 每題結束後公布答案的時間
COUNTDOWN_SECONDS = 5
SLOT = ANSWER_SECONDS + REVEAL_SECONDS


@lru_cache(maxsize=1)
def bank() -> dict[int, dict]:
    path = Path(__file__).resolve().parent.parent / "music_bank.json"
    if not path.exists():
        return {}
    return {q["id"]: q for q in json.load(open(path, encoding="utf-8"))}


def _pool(mode: str, region: str) -> list[dict]:
    if mode not in MODES or region not in REGIONS:
        raise HTTPException(400, "模式或地區不正確")
    return [q for q in bank().values() if (mode == "mix" or q["mode"] == mode) and (region == "all" or q["region"] == region)]


def _public(q: dict) -> dict:
    """不含答案；選項用題目 id 當種子洗牌，同一題每次順序一樣。"""
    opts = list(q["options"])
    random.Random(q["id"]).shuffle(opts)
    return {"id": q["id"], "mode": q["mode"], "region": q["region"], "q": q["q"], "emoji": q.get("emoji"), "options": opts}


def _reveal(q: dict) -> dict:
    query = " ".join(x for x in (q.get("song"), q.get("artist")) if x)
    return {"answer": q["answer"], "explain": q.get("explain"), "song": q.get("song"), "artist": q.get("artist"),
            "search": "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query) if query else None}


# ------------------------------------------------------------------ 單人練習
@router.get("/meta")
def meta():
    counts = {}
    for q in bank().values():
        counts[q["mode"]] = counts.get(q["mode"], 0) + 1
    return {"modes": MODES, "regions": REGIONS, "counts": counts, "total": len(bank()), "team_sizes": TEAM_SIZES,
            "round": ROUND_QUESTIONS, "answer_seconds": ANSWER_SECONDS}


@router.get("/questions")
def questions(mode: str = "mix", region: str = "all", n: int = ROUND_QUESTIONS):
    pool = _pool(mode, region)
    if not pool:
        raise HTTPException(404, "這個組合還沒有題目")
    return {"questions": [_public(q) for q in random.sample(pool, min(max(1, n), 50, len(pool)))]}


class CheckBody(BaseModel):
    id: int
    given: str


@router.post("/check", dependencies=[Depends(require_json)])
def check(body: CheckBody):
    q = bank().get(body.id)
    if not q:
        raise HTTPException(404, "找不到這一題")
    return {"correct": body.given == q["answer"], **_reveal(q)}


# ------------------------------------------------------------------ 音樂題庫（月訂閱）
@router.get("/bank")
def music_bank(mode: str = "mix", region: str = "all", q: str = "", page: int = 1,
               user: User = Depends(require_user), db: Session = Depends(get_db)):
    """登入就能瀏覽全部題目；訂閱音樂題庫的會員才看得到答案。"""
    items = _pool(mode, region)
    if q.strip():
        key = q.strip().lower()
        items = [x for x in items if key in x["q"].lower() or key in (x.get("song") or "").lower() or key in (x.get("artist") or "").lower()]
    per = 20
    pages = max(1, (len(items) + per - 1) // per)
    page = min(max(1, page), pages)
    show = music_subscribed(db, user)
    rows = []
    for x in items[(page - 1) * per: page * per]:
        row = {**_public(x), "region_name": REGIONS[x["region"]], "mode_name": MODES[x["mode"]]}
        if show:
            row.update(_reveal(x))
        rows.append(row)
    return {"total": len(items), "page": page, "pages": pages, "subscribed": show, "questions": rows}


# ------------------------------------------------------------------ 組隊對戰
def _room(db: Session, code: str) -> MusicRoom:
    room = db.scalar(select(MusicRoom).where(MusicRoom.code == code))
    if not room:
        raise HTTPException(404, "找不到這個對戰房間，請確認邀請連結")
    return room


def _clock(room: MusicRoom, now: float) -> dict:
    """依開始時間算出目前狀態：waiting／countdown／playing（answer 或 reveal 階段）／done。"""
    if room.started_at is None:
        return {"status": "waiting"}
    elapsed = now - room.started_at
    if elapsed < 0:
        return {"status": "countdown", "remaining": -elapsed}
    total = len(room.question_ids)
    index = int(elapsed // SLOT)
    if index >= total:
        return {"status": "done", "index": total}
    in_slot = elapsed - index * SLOT
    if in_slot < ANSWER_SECONDS:
        return {"status": "playing", "index": index, "phase": "answer", "remaining": ANSWER_SECONDS - in_slot}
    return {"status": "playing", "index": index, "phase": "reveal", "remaining": SLOT - in_slot}


def _player_name(db: Session, p: MusicPlayer) -> tuple[str, dict]:
    profile = profile_dict(p.user, db.get(Profile, p.user_id))
    if profile["avatar_type"] == "upload":  # 上傳的頭像不公開，對戰時改用 Google 大頭貼
        profile["avatar_type"], profile["avatar_url"] = "google", p.user.picture or ""
    return profile["nickname"] or p.user.name or p.user.email.split("@")[0], profile


def _state(db: Session, room: MusicRoom, user: User) -> dict:
    now = time.time()
    clock = _clock(room, now)
    scores: dict[int, int] = {}
    for a in room.answers:
        scores[a.user_id] = scores.get(a.user_id, 0) + a.points
    players = []
    for p in room.players:
        name, profile = _player_name(db, p)
        players.append({"user_id": p.user_id, "name": name, "profile": profile, "team": p.team, "score": scores.get(p.user_id, 0)})
    teams = {t: sum(p["score"] for p in players if p["team"] == t) for t in ("red", "blue")}
    me = next((p for p in room.players if p.user_id == user.id), None)
    state = {
        "code": room.code, "is_owner": room.owner_id == user.id, "team_size": room.team_size,
        "mode": room.mode, "mode_name": MODES.get(room.mode, room.mode), "region": room.region, "region_name": REGIONS.get(room.region, room.region),
        "total": len(room.question_ids), "answer_seconds": ANSWER_SECONDS, "reveal_seconds": REVEAL_SECONDS,
        "server_now": now, "started_at": room.started_at, **clock,
        "players": players, "teams": teams, "me": {"team": me.team} if me else None,
    }
    if clock["status"] == "playing":
        q = bank().get(room.question_ids[clock["index"]])
        if q:
            state["question"] = _public(q)
            mine = next((a for a in room.answers if a.user_id == user.id and a.q_index == clock["index"]), None)
            state["my_answer"] = {"answered": True, "correct": mine.correct, "points": mine.points} if mine and clock["phase"] == "reveal" else (
                {"answered": True} if mine else None)
            if clock["phase"] == "reveal":
                state["reveal"] = _reveal(q)
                state["round_correct"] = [a.user_id for a in room.answers if a.q_index == clock["index"] and a.correct]
    if clock["status"] == "done":
        red, blue = teams["red"], teams["blue"]
        state["winner"] = "red" if red > blue else "blue" if blue > red else "draw"
        state["mvp"] = max(players, key=lambda p: p["score"])["user_id"] if players else None
        state["review"] = [{"q": bank()[qid]["q"], "emoji": bank()[qid].get("emoji"), **_reveal(bank()[qid])}
                           for qid in room.question_ids if qid in bank()]
    return state


class RoomBody(BaseModel):
    team_size: int = 3
    mode: str = "mix"
    region: str = "all"


@router.post("/rooms", dependencies=[Depends(require_json)])
def create_room(body: RoomBody, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if body.team_size not in TEAM_SIZES:
        raise HTTPException(400, "每隊人數只能是 3、4 或 5 人")
    pool = _pool(body.mode, body.region)
    if len(pool) < ROUND_QUESTIONS:
        raise HTTPException(400, "這個模式和地區的題目不夠，換一個組合試試")
    room = MusicRoom(code=secrets.token_urlsafe(6), owner_id=user.id, team_size=body.team_size, mode=body.mode,
                     region=body.region, question_ids=[q["id"] for q in random.sample(pool, ROUND_QUESTIONS)])
    room.players.append(MusicPlayer(user_id=user.id, team="red"))
    db.add(room)
    db.commit()
    return {"code": room.code}


@router.get("/rooms/{code}")
def get_room(code: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return _state(db, _room(db, code), user)


class JoinBody(BaseModel):
    team: str | None = None


@router.post("/rooms/{code}/join", dependencies=[Depends(require_json)])
def join_room(code: str, body: JoinBody, user: User = Depends(require_user), db: Session = Depends(get_db)):
    room = _room(db, code)
    if room.started_at is not None:
        raise HTTPException(409, "對戰已經開始，不能再加入或換隊")
    counts = {t: sum(1 for p in room.players if p.team == t) for t in ("red", "blue")}
    me = next((p for p in room.players if p.user_id == user.id), None)
    if me:
        counts[me.team] -= 1
    team = body.team if body.team in ("red", "blue") else min(counts, key=lambda t: counts[t])
    if counts[team] >= room.team_size:
        raise HTTPException(409, "這一隊已經滿了，請選另一隊")
    if me:
        me.team = team
    else:
        room.players.append(MusicPlayer(user_id=user.id, team=team))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return _state(db, _room(db, code), user)


@router.post("/rooms/{code}/start", dependencies=[Depends(require_json)])
def start_room(code: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    room = _room(db, code)
    if room.owner_id != user.id:
        raise HTTPException(403, "只有房主可以開始對戰")
    if room.started_at is not None:
        raise HTTPException(409, "對戰已經開始了")
    if not all(any(p.team == t for p in room.players) for t in ("red", "blue")):
        raise HTTPException(400, "紅隊和藍隊都至少要有 1 人才能開始")
    room.started_at = time.time() + COUNTDOWN_SECONDS
    db.commit()
    return _state(db, room, user)


class AnswerBody(BaseModel):
    index: int
    given: str


@router.post("/rooms/{code}/answer", dependencies=[Depends(require_json)])
def answer_room(code: str, body: AnswerBody, user: User = Depends(require_user), db: Session = Depends(get_db)):
    room = _room(db, code)
    if not any(p.user_id == user.id for p in room.players):
        raise HTTPException(403, "你不是這場對戰的玩家")
    clock = _clock(room, time.time())
    if clock["status"] != "playing" or clock["index"] != body.index or clock["phase"] != "answer":
        raise HTTPException(409, "這一題的作答時間已經結束")
    q = bank()[room.question_ids[body.index]]
    correct = body.given == q["answer"]
    # 答對 100 分，再依剩餘時間加最多 100 分的速度獎勵
    points = 100 + round(100 * clock["remaining"] / ANSWER_SECONDS) if correct else 0
    db.add(MusicAnswer(room_id=room.id, user_id=user.id, q_index=body.index, correct=correct, points=points))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "這一題已經作答過了")
    return {"answered": True}


@router.post("/rooms/{code}/leave", dependencies=[Depends(require_json)])
def leave_room(code: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    room = _room(db, code)
    if room.started_at is not None:
        raise HTTPException(409, "對戰已經開始，不能退出")
    if room.owner_id == user.id:
        db.delete(room)
    else:
        me = next((p for p in room.players if p.user_id == user.id), None)
        if me:
            room.players.remove(me)
    db.commit()
    return {"ok": True}
