"""把題庫輸出成 PDF（嵌入 Noto Sans TC 中文字型，表情符號用 Noto Emoji 補字）。"""

import io
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from app import catalog
from app.models import Question

APP_DIR = Path(__file__).resolve().parent
FONT_DIR = APP_DIR / "fonts"
IMAGE_DIR = APP_DIR / "static" / "images"

PINK = colors.HexColor("#e8508a")
MUTED = colors.HexColor("#a07f8f")
TEXT = colors.HexColor("#5a3d4c")
SOFT = colors.HexColor("#fff0f5")

DIFF_LABEL = {"easy": "簡單", "medium": "中等", "hard": "困難"}
TYPE_LABEL = {"single": "單選題", "image": "圖片題", "short": "簡答題", "qa": "問答題"}
# 變化選擇符與零寬連接符在 PDF 裡沒有字形，直接拿掉
INVISIBLE = {0xFE0F, 0xFE0E, 0x200D}


@lru_cache
def _fonts() -> tuple[set[int], set[int]]:
    regular = TTFont("NotoSansTC", str(FONT_DIR / "NotoSansTC-Regular.ttf"))
    bold = TTFont("NotoSansTC-Bold", str(FONT_DIR / "NotoSansTC-Bold.ttf"))
    emoji = TTFont("NotoEmoji", str(FONT_DIR / "NotoEmoji-Regular.ttf"))
    for font in (regular, bold, emoji):
        pdfmetrics.registerFont(font)
    pdfmetrics.registerFontFamily("NotoSansTC", normal="NotoSansTC", bold="NotoSansTC-Bold")
    return set(regular.face.charToGlyph), set(emoji.face.charToGlyph)


def rich(text: str) -> str:
    """跳脫 XML，並把中文字型沒有、但 Noto Emoji 有的字元改用 Emoji 字型。"""
    cjk, emoji = _fonts()
    out, run = [], []

    def flush():
        if run:
            out.append(f'<font name="NotoEmoji">{escape("".join(run))}</font>')
            run.clear()

    for ch in str(text or ""):
        cp = ord(ch)
        if cp in INVISIBLE:
            continue
        if cp not in cjk and cp in emoji:
            run.append(ch)
        else:
            flush()
            out.append(escape(ch))
    flush()
    return "".join(out).replace("\n", "<br/>")


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="NotoSansTC", fontSize=10.5, leading=16, textColor=TEXT)
    return {
        "title": ParagraphStyle("title", parent=base, fontName="NotoSansTC-Bold", fontSize=22, leading=30, textColor=PINK, alignment=TA_CENTER),
        "sub": ParagraphStyle("sub", parent=base, fontSize=9.5, textColor=MUTED, alignment=TA_CENTER),
        "meta": ParagraphStyle("meta", parent=base, fontSize=8.5, leading=12, textColor=MUTED),
        "q": ParagraphStyle("q", parent=base, fontName="NotoSansTC-Bold", fontSize=11.5, leading=17, spaceBefore=2),
        "emoji": ParagraphStyle("emoji", parent=base, fontSize=22, leading=30, spaceBefore=4, spaceAfter=2),
        "opt": ParagraphStyle("opt", parent=base, leftIndent=12),
        "ans": ParagraphStyle("ans", parent=base, backColor=SOFT, borderPadding=(4, 6, 4, 6), leftIndent=6, rightIndent=6, spaceBefore=6),
    }


def _image(q: Question):
    path = (IMAGE_DIR / q.img).resolve()
    if path.parent != IMAGE_DIR or not path.is_file():
        return None
    img = Image(str(path))
    scale = min(70 * mm / img.imageWidth, 50 * mm / img.imageHeight)
    img.drawWidth, img.drawHeight = img.imageWidth * scale, img.imageHeight * scale
    img.hAlign = "LEFT"
    return img


def _question_block(n: int, q: Question, s: dict) -> KeepTogether:
    meta = f"{catalog.CATEGORIES[q.cat]}　｜　{DIFF_LABEL[q.difficulty]}　｜　{TYPE_LABEL[q.type]}"
    parts = [Paragraph(rich(meta), s["meta"]), Paragraph(rich(f"{n}. {q.q}"), s["q"])]
    if q.emoji:
        parts.append(Paragraph(rich(q.emoji), s["emoji"]))
    if q.img and (img := _image(q)):
        parts += [Spacer(1, 3), img]
    options = catalog.stable_options(q)
    if options:
        letters = "ABCDEFGH"
        parts += [Paragraph(rich(f"({letters[i]}) {o}"), s["opt"]) for i, o in enumerate(options)]
    if q.type in ("short", "qa"):
        parts.append(Paragraph(rich("作答：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿"), s["opt"]))
    if q.type == "short":
        answer = "可接受：" + "／".join(q.accept or [])
    elif options:
        answer = f"({'ABCDEFGH'[options.index(q.answer)]}) {q.answer}"
    else:
        answer = catalog.correct_answer_text(q)
    label = "參考答案" if q.type == "qa" else "答案"
    text = f"<b>{label}</b>　{rich(answer)}"
    if q.explain:
        text += f"<br/>{rich(q.explain)}"
    parts.append(Paragraph(text, s["ans"]))
    parts.append(Spacer(1, 12))
    return KeepTogether(parts)


def build_pdf(questions: list[Question], *, owner: str, filters: str) -> bytes:
    """訂閱會員專屬：每題都附答案與解說。"""
    _fonts()
    s = _styles()
    buf = io.BytesIO()
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("NotoSansTC", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"知識大挑戰・授權給 {owner}・僅供個人使用")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"第 {doc.page} 頁")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title="知識大挑戰 題庫", author="知識大挑戰",
    )
    story = [
        Paragraph(rich("🎀 知識大挑戰・題庫"), s["title"]),
        Paragraph(rich(f"{filters}・共 {len(questions)} 題・匯出時間 {now}"), s["sub"]),
        Spacer(1, 14),
    ]
    story += [_question_block(i, q, s) for i, q in enumerate(questions, 1)]
    if not questions:
        story.append(Paragraph("沒有符合篩選條件的題目。", s["sub"]))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
