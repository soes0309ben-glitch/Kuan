"""把 LINE 上打的一句話解析成「記一筆」或「指令」。

支援的寫法（全形半形都可以）：
    午餐 120            → 支出 120，自動歸到「餐飲」
    120 午餐            → 金額放前面也可以
    計程車250           → 不用空格
    昨天 晚餐 300 / 10/3 電影 350 / 3月5日 房租 15000
    +50000 薪水 / 收入 獎金 3000 / 薪水 50000（命中收入關鍵字自動算收入）
    蝦皮 耳機 1.2k / 機票 1.5萬
    咖啡 65 #餐飲        → 用 # 指定分類
    一次傳多行，每行記一筆
"""

import datetime
import re
import unicodedata
from dataclasses import dataclass, field

MAX_AMOUNT = 100_000_000


@dataclass
class Entry:
    amount: int
    note: str
    occurred_on: datetime.date
    # None 表示由內容判斷（命中收入關鍵字才算收入）
    kind: str | None = None
    category_hint: str | None = None


@dataclass
class Command:
    name: str
    args: list[str] = field(default_factory=list)


@dataclass
class ParseResult:
    entries: list[Entry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    command: Command | None = None


COMMANDS = {
    "help": ("說明", "幫助", "help", "?", "使用說明", "教學", "指令"),
    "today": ("今天", "今日"),
    "yesterday": ("昨天", "昨日"),
    "week": ("本週", "這週", "本周", "這周", "週報"),
    "month": ("本月", "這個月", "這月", "月報", "統計"),
    "last_month": ("上月", "上個月"),
    "recent": ("明細", "最近", "紀錄", "記錄", "清單"),
    "budget": ("預算",),
    "undo": ("復原", "取消", "undo", "刪除上一筆", "刪除", "撤銷"),
    "categories": ("分類", "類別"),
    "web": ("網頁", "報表", "app", "登入", "web"),
    "reminder": ("提醒",),
}
_COMMAND_LOOKUP = {alias.lower(): name for name, aliases in COMMANDS.items() for alias in aliases}

_RELATIVE_DAYS = {"今天": 0, "今日": 0, "昨天": 1, "昨日": 1, "前天": 2, "大前天": 3}
_DATE_SLASH = re.compile(r"(?<![\d.])(?:(\d{4})[/-])?(\d{1,2})/(\d{1,2})(?![\d/])")
_DATE_CJK = re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日號号]?")
# 金額：可帶 $、NT$、千分位、小數、k/K/千/萬/w 單位，以及「元/塊」。
# 前後只排除英數字（中文字可以緊貼，例如「計程車250」）
_AMOUNT = re.compile(
    r"(?<![A-Za-z0-9.])(?:nt\$|\$)?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s*(k|千|萬|w)?(?:元|塊錢|塊)?(?![A-Za-z0-9.])",
    re.IGNORECASE,
)
_CATEGORY_TAG = re.compile(r"#\s*(\S+)")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def _resolve_date(year: str | None, month: str, day: str, today: datetime.date) -> datetime.date | None:
    try:
        d = datetime.date(int(year) if year else today.year, int(month), int(day))
    except ValueError:
        return None
    if not year and d > today:
        # 沒寫年份又比今天晚，多半是指去年（例如一月初補記 12/30）
        try:
            d = d.replace(year=d.year - 1)
        except ValueError:
            return None
    return d


def _parse_amount(m: re.Match) -> int | None:
    whole = m.group(1).replace(",", "")
    frac = m.group(2) or ""
    unit = (m.group(3) or "").lower()
    value = float(f"{whole}.{frac}" if frac else whole)
    value *= {"k": 1000, "千": 1000, "萬": 10000, "w": 10000}.get(unit, 1)
    amount = round(value)
    return amount if 0 < amount <= MAX_AMOUNT else None


def parse_entry(line: str, today: datetime.date) -> Entry | str:
    """解析一行記帳文字；失敗時回傳錯誤說明（字串）。"""
    text = normalize(line)
    if not text:
        return "內容是空的"

    kind = None
    if text[0] in "+-":
        kind, text = ("income" if text[0] == "+" else "expense"), text[1:].strip()
    for prefix, k in (("收入", "income"), ("支出", "expense"), ("花費", "expense")):
        if text.startswith(prefix):
            kind, text = k, text[len(prefix):].strip()
            break

    category_hint = None
    if m := _CATEGORY_TAG.search(text):
        category_hint = m.group(1)
        text = (text[: m.start()] + " " + text[m.end():]).strip()

    occurred_on = today
    for word, delta in sorted(_RELATIVE_DAYS.items(), key=lambda kv: -len(kv[0])):
        if word in text:
            occurred_on = today - datetime.timedelta(days=delta)
            text = text.replace(word, " ", 1)
            break
    else:
        for pattern in (_DATE_SLASH, _DATE_CJK):
            if m := pattern.search(text):
                d = _resolve_date(m.group(1), m.group(2), m.group(3), today)
                if not d:
                    return f"日期「{m.group(0)}」不存在"
                occurred_on = d
                text = (text[: m.start()] + " " + text[m.end():]).strip()
                break

    matches = list(_AMOUNT.finditer(text))
    if not matches:
        return "找不到金額"
    # 備註裡也可能有數字（7-11、iPhone 16），金額取最後一個數字
    m = matches[-1]
    amount = _parse_amount(m)
    if amount is None:
        return f"金額需介於 1 到 {MAX_AMOUNT:,} 元"
    note = (text[: m.start()] + " " + text[m.end():]).strip()
    note = re.sub(r"\s+", " ", note).strip(" ,，、:：")
    return Entry(amount=amount, note=note[:200], occurred_on=occurred_on, kind=kind, category_hint=category_hint)


def parse_message(text: str, today: datetime.date) -> ParseResult:
    text = normalize(text)
    words = text.split()
    if words:
        first = words[0].lower()
        name = _COMMAND_LOOKUP.get(first)
        # 「刪除 3」之類有數字參數，或只有指令本身，才當指令；「今天 午餐 120」要當記帳
        if name and (len(words) == 1 or name in ("budget", "reminder", "undo") or not _AMOUNT.search(text)):
            return ParseResult(command=Command(name, words[1:]))

    result = ParseResult()
    for raw in text.splitlines():
        if not raw.strip():
            continue
        parsed = parse_entry(raw, today)
        if isinstance(parsed, Entry):
            result.entries.append(parsed)
        else:
            result.errors.append(f"「{raw.strip()[:30]}」：{parsed}")
    return result
