"""題庫：匯入、出題、判分、輸出給前端（不含答案）。"""

import random
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DIFFICULTIES, Question

CATEGORIES = {
    "anime": "動漫動畫",
    "life": "生活常識",
    "history": "歷史",
    "travel": "旅遊地理",
    "riddle": "猜謎",
    "animal": "動物生活",
    "trivia": "冷知識",
    "language": "語言",
    "japan": "日系文化",
    "korea": "韓系潮流",
    "biology": "生物科學",
    "health": "醫療保健",
}
MIXED = "all"  # 綜合挑戰：從所有主題出題
TYPES = ("single", "image", "short", "qa")
CHOICE_TYPES = ("single", "image")

# 每次挑戰的題數與題型配比（不足時用其他題型補滿）
QUESTIONS_PER_ATTEMPT = 30
TYPE_MIX = {"single": 15, "image": 6, "short": 6, "qa": 3}


class ImportError_(ValueError):
    pass


def validate(item: dict, index: int) -> dict:
    def fail(msg: str):
        raise ImportError_(f"第 {index + 1} 題：{msg}（{str(item.get('q', ''))[:30]}）")

    if item.get("cat") not in CATEGORIES:
        fail("cat 不正確")
    if item.get("type") not in TYPES:
        fail("type 必須是 single / image / short / qa")
    if item.get("difficulty") not in DIFFICULTIES:
        fail("difficulty 必須是 easy / medium / hard")
    if not str(item.get("q", "")).strip():
        fail("缺少題目 q")
    if item["type"] in CHOICE_TYPES:
        options = item.get("options") or []
        if len(options) < 2 or item.get("answer") not in options:
            fail("選擇題需要 options，且 answer 必須在 options 裡")
        if len(set(options)) != len(options):
            fail("選項重複")
    if item["type"] == "image" and not (item.get("img") or item.get("emoji")):
        fail("圖片題需要 img 或 emoji")
    if item["type"] == "short" and not item.get("accept"):
        fail("簡答題需要 accept")
    if item["type"] == "qa" and not item.get("ref"):
        fail("問答題需要 ref 參考答案")
    return item


FIELDS = ("cat", "type", "difficulty", "q", "options", "answer", "accept", "ref", "explain", "img", "emoji")


def _natural_key(item: dict) -> tuple:
    return (item["cat"], item["q"], item.get("emoji") or "", item.get("img") or "")


def import_questions(db: Session, items: list[dict]) -> dict:
    """依「主題＋題目內容」比對：已存在就更新，不存在就新增。不會刪題，以免影響已作答紀錄。"""
    items = [validate(item, i) for i, item in enumerate(items)]
    existing = {
        _natural_key({"cat": q.cat, "q": q.q, "emoji": q.emoji, "img": q.img}): q
        for q in db.scalars(select(Question))
    }
    added = updated = 0
    for item in items:
        data = {f: item.get(f) for f in FIELDS}
        row = existing.get(_natural_key(item))
        if row:
            for f, v in data.items():
                setattr(row, f, v)
            updated += 1
        else:
            row = Question(**data)
            db.add(row)
            existing[_natural_key(item)] = row
            added += 1
    db.commit()
    return {"added": added, "updated": updated}


def pick_questions(db: Session, category: str, difficulty: str, rng: random.Random | None = None) -> list[int]:
    rng = rng or random.Random()
    stmt = select(Question.id, Question.type).where(Question.difficulty == difficulty)
    if category != MIXED:
        stmt = stmt.where(Question.cat == category)
    rows = db.execute(stmt).all()
    by_type: dict[str, list[int]] = {t: [] for t in TYPES}
    for qid, qtype in rows:
        by_type[qtype].append(qid)
    chosen: list[int] = []
    for qtype, n in TYPE_MIX.items():
        pool = by_type[qtype]
        chosen += rng.sample(pool, min(n, len(pool)))
    leftovers = [qid for qid, _ in rows if qid not in set(chosen)]
    chosen += rng.sample(leftovers, min(QUESTIONS_PER_ATTEMPT - len(chosen), len(leftovers)))
    rng.shuffle(chosen)
    return chosen


def public_question(q: Question, rng: random.Random | None = None) -> dict:
    """給作答畫面用：不含答案、可接受寫法、參考答案、圖片檔名。"""
    rng = rng or random.Random()
    data = {
        "id": q.id,
        "cat": q.cat,
        "type": q.type,
        "difficulty": q.difficulty,
        "q": q.q,
        "emoji": q.emoji,
        "img": f"/api/media/{q.id}" if q.img else None,
    }
    if q.type in CHOICE_TYPES:
        options = list(q.options or [])
        rng.shuffle(options)
        data["options"] = options
    return data


def stable_options(q: Question) -> list[str] | None:
    """題庫總覽與 PDF 用：每題固定一種打亂順序（題庫裡正解都寫在第一個，不能照原順序顯示）。"""
    if not q.options:
        return None
    options = list(q.options)
    random.Random(q.id).shuffle(options)
    return options


def full_question(q: Question, *, reveal: bool) -> dict:
    """題庫總覽用；reveal=False 時隱藏答案。"""
    data = public_question(q)
    data["options"] = stable_options(q)
    if reveal:
        data.update(answer=correct_answer_text(q), explain=q.explain, ref=q.ref)
    return data


def correct_answer_text(q: Question) -> str:
    if q.type == "short":
        return (q.accept or [""])[0]
    if q.type == "qa":
        return q.ref or ""
    return q.answer or ""


_STRIP = re.compile(r"[\s·・．.,，。、!?！？「」『』《》〈〉()（）'\"“”‘’\-—:：;；~～]")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text)).lower().replace("臺", "台")
    return _STRIP.sub("", text)


def check_short(given: str, accept: list[str]) -> bool:
    n = normalize(given)
    if not n:
        return False
    for a in accept:
        na = normalize(a)
        # 允許稍微多寫幾個字（如「是富士山」），但單字答案必須完全相同
        if n == na or (len(na) >= 2 and len(n) <= len(na) + 4 and na in n):
            return True
    return False


def grade(q: Question, given: str) -> float | None:
    """回傳分數；問答題回傳 None，等使用者自評。"""
    if q.type in CHOICE_TYPES:
        return 1.0 if given == q.answer else 0.0
    if q.type == "short":
        return 1.0 if check_short(given, q.accept or []) else 0.0
    return None
