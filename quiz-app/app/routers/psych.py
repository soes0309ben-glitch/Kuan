"""心理測驗：隨機抽題、伺服器計分；登入後保存結果，可分享，默契配對可和朋友比較。"""

import random
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user, require_json, require_user
from app.models import Profile, PsychIllust, PsychResult, User
from app.psych_data import DISCLAIMER, TESTS

router = APIRouter(prefix="/api/psych")


# 綜合心理測驗：從每個測驗各抽幾題（16 型每個維度兩題），題目 id 編成「測驗序號 × 1000 + 原 id」
MIX = "mix"
MIX_PICK = {"lovebrain": 3, "lovetype": 3, "animal": 3, "type16": 8, "match": 3, "career": 3, "psychopath": 3, "romance": 3, "scent": 3, "cat": 3, "taiwan": 3}
MIX_ORDER = list(MIX_PICK)
MIX_INFO = {
    "title": "綜合心理測驗",
    "subtitle": "11 個測驗一次測完，看見完整的你",
    "emoji": "🔮",
    "theme": "sunny",
    "intro": "從戀愛腦、戀愛類型、動物性格、16 型人格、默契、職涯、心理變態指數、浪漫症快篩、戀愛香氣、貓系人格和台灣風景 11 個測驗各抽幾題，一次拼出你的性格全貌！",
}


def _test(slug: str) -> dict:
    test = TESTS.get(slug)
    if not test:
        raise HTTPException(404, "找不到這個測驗")
    return test


def _illusts(db: Session) -> dict[str, int]:
    """有插畫的測驗與更新時間（當作快取版本號）。"""
    return {i.slug: int(i.updated_at.timestamp()) if i.updated_at else 0 for i in db.scalars(select(PsychIllust))}


def _illust_url(slug: str, illusts: dict) -> str | None:
    return f"/api/psych/illust/{slug}?v={illusts[slug]}" if slug in illusts else None


@router.get("")
def list_tests(db: Session = Depends(get_db)):
    illusts = _illusts(db)
    return {
        "mix": {**MIX_INFO, "slug": MIX, "count": sum(MIX_PICK.values()),
                "emojis": [TESTS[s]["emoji"] for s in MIX_ORDER]},
        "tests": [
            {"slug": slug, "title": t["title"], "subtitle": t["subtitle"], "emoji": t["emoji"],
             "theme": t["theme"], "count": len(t["questions"]), "illust": _illust_url(slug, illusts)}
            for slug, t in TESTS.items()
        ]
    }


@router.get("/illust/{slug}")
def illust(slug: str, db: Session = Depends(get_db)):
    item = db.get(PsychIllust, slug)
    if not item:
        raise HTTPException(404)
    return Response(item.data, media_type=item.mime,
                    headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"})


@router.get("/{slug}")
def get_test(slug: str, n: int = 0, seed: int | None = None, db: Session = Depends(get_db)):
    """n=0 代表全部題目；其他數字代表隨機抽 n 題。選項只給文字，計分留在伺服器。"""
    rng = random.Random(seed)
    if slug == MIX:
        return _mix_test(rng)
    test = _test(slug)
    questions = _sample(test, n, rng)
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
        "illust": _illust_url(slug, _illusts(db)),
        "questions": [{"id": q["id"], "q": q["q"], "options": [o["t"] for o in q["options"]]} for q in questions],
    }


def _sample(test: dict, n: int, rng: random.Random) -> list[dict]:
    questions = list(test["questions"])
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
    return questions


def _mix_test(rng: random.Random) -> dict:
    questions = []
    for i, slug in enumerate(MIX_ORDER):
        for q in _sample(TESTS[slug], MIX_PICK[slug], rng):
            questions.append({"id": (i + 1) * 1000 + q["id"], "q": q["q"], "options": [o["t"] for o in q["options"]]})
    rng.shuffle(questions)
    return {**MIX_INFO, "slug": MIX, "kind": MIX, "disclaimer": DISCLAIMER, "total": len(questions), "fixed": True,
            "axes": None, "illust": None, "questions": questions}


def score_mix(answers: list[tuple[int, int]]) -> dict:
    """把作答拆回各測驗分別計分，再組成一份綜合結果。"""
    groups: dict[str, list[tuple[int, int]]] = {}
    for qid, idx in answers:
        i = qid // 1000 - 1
        if not 0 <= i < len(MIX_ORDER):
            raise HTTPException(400, "作答資料不正確")
        groups.setdefault(MIX_ORDER[i], []).append((qid % 1000, idx))
    if not groups:
        raise HTTPException(400, "請至少回答一題")
    parts = {slug: score(slug, groups[slug]) for slug in MIX_ORDER if slug in groups}
    summary = []
    for slug, r in parts.items():
        extra = f"{r['index']}%" if r["kind"] == "index" else r.get("holland") or (r["type_key"] if r["kind"] == "dimension" else None)
        summary.append({"slug": slug, "title": TESTS[slug]["title"], "emoji": TESTS[slug]["emoji"],
                        "type": {"name": r["type"]["name"], "emoji": r["type"]["emoji"]}, "extra": extra})

    def dim_pct(letter: str) -> int:
        dims = parts.get("type16", {}).get("dims", [])
        # 每個維度只有兩題，分數很跳；收斂到 15～85%，表示「偏向」而不是絕對
        return round(15 + 0.7 * next((d["a_pct"] for d in dims if d["a"] == letter), 50))

    axes = [
        ("love", "戀愛腦", "談戀愛時投入的程度", parts["lovebrain"]["index"] if "lovebrain" in parts else 50),
        ("dark", "黑暗面", "冷靜、自我、敢衝的那一面", parts["psychopath"]["index"] if "psychopath" in parts else 50),
        ("romance", "浪漫", "替生活加上儀式感與小確幸", parts["romance"]["index"] if "romance" in parts else 50),
        ("extra", "外向", "從人群中獲得能量", dim_pct("E")),
        ("logic", "理性", "用邏輯做決定", dim_pct("T")),
        ("plan", "計畫性", "喜歡事先安排好", dim_pct("J")),
    ]
    animal = parts.get("animal") or next(iter(parts.values()))
    t16 = parts.get("type16")
    name = animal["type"]["name"] + (f" × {t16['type']['name']}" if t16 else "")
    desc = "、".join(f"{s['emoji']}{s['type']['name']}" for s in summary)
    return {
        "slug": MIX, "kind": MIX, "title": MIX_INFO["title"], "theme": MIX_INFO["theme"], "answered": len(answers),
        "type_key": animal["type_key"],
        "type": {"name": name, "emoji": animal["type"]["emoji"], "desc": f"你的綜合人格由這些結果組成：{desc}。"},
        "axes": [{"key": k, "name": n, "desc": d, "pct": v} for k, n, d, v in axes],
        "parts": summary,
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
    if result["type"].get("friend"):  # 浪漫之友：最合拍的類型
        result["friend"] = {"key": result["type"]["friend"], **test["types"][result["type"]["friend"]]}

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
    pairs = [(a.q, a.o) for a in body.answers]
    result = score_mix(pairs) if slug == MIX else score(slug, pairs)
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
    return {**result, "illust": _illust_url(slug, _illusts(db))}


@router.get("/r/{code}")
def shared_result(code: str, db: Session = Depends(get_db)):
    """分享出去的結果頁：任何人都能看（只顯示暱稱，不顯示 Email）。"""
    r = db.scalar(select(PsychResult).where(PsychResult.code == code))
    if not r:
        raise HTTPException(404, "找不到這個測驗結果")
    return {**r.result, "code": r.code, "owner": _owner_name(db, r), "illust": _illust_url(r.slug, _illusts(db))}


@router.get("/me/results")
def my_results(user: User = Depends(require_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(PsychResult).where(PsychResult.user_id == user.id).order_by(PsychResult.created_at.desc()).limit(30)
    )
    return {"results": [{"code": r.code, "slug": r.slug, "title": MIX_INFO["title"] if r.slug == MIX else TESTS.get(r.slug, {}).get("title", r.slug),
                         "type": r.result.get("type"), "index": r.result.get("index"),
                         "created_at": r.created_at.isoformat()} for r in rows]}
