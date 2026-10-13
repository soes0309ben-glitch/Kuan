"""內容翻譯：心理測驗與音樂題目的文字依介面語言（請求標頭 X-Lang）換成對應語言。

翻譯檔在 app/i18n_content/<語言>.json（{中文原文: 譯文}），由 seed/i18n/ 的流程產生；
專有名詞（外國歌手、動漫作品）在 _names.json，和語言無關，一律換成原文名稱。
簡體中文不需要翻譯檔，直接用 OpenCC 把繁體轉成簡體。
"""
import json
import re
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent / "i18n_content"
CJK = re.compile(r"[一-鿿]")
PH = re.compile(r"\{(\d+)\}")
NATIVE = {"", "zh", "zh-hant", "zh-tw"}


def norm_lang(lang: str | None) -> str:
    return (lang or "").strip().lower()


@lru_cache(maxsize=1)
def names() -> dict[str, str]:
    path = DIR / "_names.json"
    return json.load(open(path, encoding="utf-8")) if path.exists() else {}


@lru_cache(maxsize=40)
def table(lang: str):
    """回傳 (完整對照表, 句型清單, 片段替換用的正規式)；沒有翻譯檔時回傳 None。"""
    path = DIR / f"{lang}.json"
    if not path.exists():
        return None
    exact = {k: v for k, v in json.load(open(path, encoding="utf-8")).items() if v}
    templates = []
    for src, dst in exact.items():
        if PH.search(src):
            parts = PH.split(src)  # 文字、編號、文字、編號……
            pattern = "".join(re.escape(p) if i % 2 == 0 else f"(?P<g{p}>.+?)" for i, p in enumerate(parts))
            templates.append((re.compile(f"^{pattern}$", re.S), dst))
    templates.sort(key=lambda t: -len(t[0].pattern))
    keys = sorted((k for k in exact if len(k) >= 2 and not PH.search(k)), key=len, reverse=True)
    pieces = re.compile("|".join(map(re.escape, keys))) if keys else None
    return exact, templates, pieces


@lru_cache(maxsize=1)
def _opencc():
    import opencc
    return opencc.OpenCC("tw2sp")


@lru_cache(maxsize=50000)
def tr_str(s: str, lang: str, loose: bool = False) -> str:
    """loose：認不出整句時，逐段替換認得的片段（只用在心理測驗，避免把歌名拆開亂換）。"""
    if not s or not CJK.search(s):
        return s
    if lang == "zh-hans":
        try:
            return _opencc().convert(s)
        except ImportError:
            return s
    t = table(lang)
    if t is None:
        return s
    exact, templates, pieces = t
    key = s.strip()
    if key in exact:
        return s.replace(key, exact[key])
    if key in names():
        return names()[key]
    for rx, dst in templates:
        m = rx.match(key)
        if m:
            return PH.sub(lambda g: tr_str(m.group(f"g{g.group(1)}"), lang, loose), dst)
    if loose and pieces:  # 組合字串（例如「💘 戀愛腦指數測驗」）：逐段替換認得的部分
        return pieces.sub(lambda m: exact[m.group(0)], s)
    return s


def translate(obj, lang: str | None, loose: bool = False):
    lang = norm_lang(lang)
    if lang in NATIVE:
        return obj
    if isinstance(obj, str):
        return tr_str(obj, lang, loose)
    if isinstance(obj, list):
        return [translate(x, lang, loose) for x in obj]
    if isinstance(obj, dict):
        return {k: translate(v, lang, loose) for k, v in obj.items()}
    return obj
