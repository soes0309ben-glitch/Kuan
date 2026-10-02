"""心理測驗：隨機抽題、伺服器計分；登入後保存結果，可分享，默契配對可和朋友比較。"""

import random
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user, require_json, require_user
from app.models import Profile, PsychResult, User
from app.psych_data import DISCLAIMER, TESTS

router = APIRouter(prefix="/api/psych")


def _test(slug: str) -> dict:
    test = TESTS.get(slug)
    if not test:
        raise HTTPException(404, "找不到這個測驗")
    return test


@router.get("")
def list_tests():
    return {
        "tests": [
            {"slug": slug, "title": t["title"], "subtitle": t["subtitle"], "emoji": t["emoji"],
             "theme": t["theme"], "count": len(t["questions"])}
            for slug, t in TESTS.items()
        ]
    }


@router.get("/{slug}")
def get_test(slug: str, n: int = 0, seed: int | None = None):
    """n=0 代表全部題目；其他數字代表隨機抽 n 題。選項只給文字，計分留在伺服器。"""
    test = _test(slug)
    questions = list(test["questions"])
    rng = random.Random(seed)
    if 0 < n < len(questions):
        if test["kind"] == "dimension":
            # 16 型：每個維度平均抽題，避免某個維度沒有題目
            per = max(1, n // len(test["pairs"]))
            groups = {}
            for q in questions:
                groups.setdefault(next(iter(q["options"][0]["s"])) + next(iter(q["options"][1]["s"])), []).append(q)
            questions = [q for g in groups.values() for q in rng.sample(g, min(per, len(g)))]
        else:
            questions = rng.sample(questions, n)
    rng.shuffle(questions)
    return {
        "slug": slug,
        "title": test["title"],
        "subtitle": test["subtitle"],
        "emoji": test["emoji"],
        "theme": test["theme"],
        "kind": test["kind"],
        "intro": test["intro"],
        "disclaimer": DISCLAIMER,
        "total": len(test["questions"]),
        "axes": test.get("axes"),
        "questions": [{"id": q["id"], "q": q["q"], "options": [o["t"] for o in q["options"]]} for q in questions],
    }


def score(slug: str, answers: list[tuple[int, int]]) -> dict:
    """answers：[(題目 id, 選項索引)]。回傳各特性百分比、類型、指數與等級。"""
    test = _test(slug)
    by_id = {q["id"]: q for q in test["questions"]}
    got: dict[str, float] = {}
    best: dict[str, float] = {}
    for qid, idx in answers:
        q = by_id.get(qid)
        if not q or not 0 <= idx < len(q["options"]):
            raise HTTPException(400, "作答資料不正確")
        # 每題每個特性可拿到的最高分，用來換算百分比
        for axis in {a for o in q["options"] for a in o["s"]}:
            best.setdefault(axis, 0)
            best[axis] += max(o["s"].get(axis, 0) for o in q["options"])
        for axis, pts in q["options"][idx]["s"].items():
            got[axis] = got.get(axis, 0) + pts
    if not answers:
        raise HTTPException(400, "請至少回答一題")

    kind = test["kind"]
    result: dict = {"slug": slug, "kind": kind, "title": test["title"], "theme": test["theme"], "answered": len(answers)}

    if kind == "dimension":
        letters, dims = "", []
        for a, b in test["pairs"]:
            va, vb = got.get(a, 0), got.get(b, 0)
            total = va + vb or 1
            pick = a if va >= vb else b
            letters += pick
            dims.append({"a": a, "b": b, "a_name": test["letters"][a], "b_name": test["letters"][b],
                         "a_pct": round(va * 100 / total), "pick": pick})
        t = test["types"][letters]
        result.update(type_key=letters, type=t, dims=dims)
        return result

    axes = test["axes"]
    pct = {k: round(got.get(k, 0) * 100 / best[k]) if best.get(k) else 0 for k in axes}
    result["axes"] = [{"key": k, "name": v["name"], "desc": v["desc"], "pct": pct[k]} for k, v in axes.items()]
    order = sorted(axes, key=lambda k: (-pct[k], list(axes).index(k)))
    result["type_key"] = order[0]
    result["type"] = test["types"][order[0]]

    if kind == "index":
        answered_axes = [k for k in axes if best.get(k)]
        index = round(sum(got.get(k, 0) for k in answered_axes) * 100 / sum(best[k] for k in answered_axes))
        result["index"] = index
        result["level"] = next(lv for lv in test["levels"] if index <= lv["max"])
        result["level_no"] = test["levels"].index(result["level"]) + 1
        result["levels"] = len(test["levels"])
    elif kind == "holland":
        top3 = order[:3]
        # 注意：不能叫 code，那是分享連結用的欄位
        result["holland"] = "".join(top3)
        result["top"] = [{"key": k, **test["types"][k]} for k in top3]
    elif kind == "match":
        result["best"] = [{"key": k, **test["types"][k]} for k in test["types"][order[0]]["best"]]
    return result


def compatibility(a: dict, b: dict) -> int:
    """兩人在各特性百分比的差距越小，默契越高（0～100）。"""
    pa = {x["key"]: x["pct"] for x in a["axes"]}
    pb = {x["key"]: x["pct"] for x in b["axes"]}
    diff = sum(abs(pa[k] - pb.get(k, 0)) for k in pa) / len(pa)
    bonus = 10 if a["type_key"] == b["type_key"] or b["type_key"] in [x["key"] for x in a.get("best", [])] else 0
    return max(0, min(100, round(100 - diff * 1.2 + bonus)))


def _owner_name(db: Session, r: PsychResult) -> str:
    if not r.user:
        return "神秘玩家"
    p = db.get(Profile, r.user_id)
    return (p and p.nickname) or r.user.name or "玩家"


class Answer(BaseModel):
    q: int
    o: int


class SubmitBody(BaseModel):
    answers: list[Answer]
    with_code: str | None = None


@router.post("/{slug}/submit", dependencies=[Depends(require_json)])
def submit(slug: str, body: SubmitBody, user: User | None = Depends(get_current_user), db: Session = Depends(get_db)):
    result = score(slug, [(a.q, a.o) for a in body.answers])
    if body.with_code:
        partner = db.scalar(select(PsychResult).where(PsychResult.code == body.with_code))
        if partner and partner.slug == slug == "match":
            result["partner"] = {
                "name": _owner_name(db, partner),
                "type": partner.result["type"],
                "compat": compatibility(result, partner.result),
            }
    if user:
        saved = PsychResult(user_id=user.id, slug=slug, result=result, code=secrets.token_urlsafe(8))
        db.add(saved)
        db.commit()
        result["code"] = saved.code
    return result


@router.get("/r/{code}")
def shared_result(code: str, db: Session = Depends(get_db)):
    """分享出去的結果頁：任何人都能看（只顯示暱稱，不顯示 Email）。"""
    r = db.scalar(select(PsychResult).where(PsychResult.code == code))
    if not r:
        raise HTTPException(404, "找不到這個測驗結果")
    return {**r.result, "code": r.code, "owner": _owner_name(db, r)}


@router.get("/me/results")
def my_results(user: User = Depends(require_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(PsychResult).where(PsychResult.user_id == user.id).order_by(PsychResult.created_at.desc()).limit(30)
    )
    return {"results": [{"code": r.code, "slug": r.slug, "title": TESTS.get(r.slug, {}).get("title", r.slug),
                         "type": r.result.get("type"), "index": r.result.get("index"),
                         "created_at": r.created_at.isoformat()} for r in rows]}
