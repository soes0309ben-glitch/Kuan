from contextlib import asynccontextmanager
from pathlib import Path

import json

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.content_i18n import NATIVE, norm_lang, translate
from app.db import init_db
from app.routers import admin, auth, music, payments, profile, psych, quiz, teams

settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="quiz_session",
    same_site="lax",
    https_only=settings.base_url.startswith("https://"),
    max_age=60 * 60 * 24 * 30,
)


@app.middleware("http")
async def translate_content(request: Request, call_next):
    """心理測驗、音樂題目依介面語言翻譯；簡體中文則全站 API 都轉成簡體。"""
    response = await call_next(request)
    lang = norm_lang(request.headers.get("x-lang"))
    path = request.url.path
    psych_path = path.startswith("/api/psych")
    if lang in NATIVE or not (psych_path or path.startswith("/api/music") or (lang == "zh-hans" and path.startswith("/api/"))):
        return response
    # 錯誤訊息交給前端的介面翻譯（T）處理，這裡不動
    if response.status_code >= 400 and lang != "zh-hans" or not response.headers.get("content-type", "").startswith("application/json"):
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    try:
        data = translate(json.loads(body), lang, loose=psych_path)
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    except ValueError:
        pass
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    return Response(body, status_code=response.status_code, headers=headers, media_type="application/json")


app.include_router(auth.router)
app.include_router(quiz.router)
app.include_router(payments.router)
app.include_router(admin.router)
app.include_router(admin.token_router)
app.include_router(profile.router)
app.include_router(teams.router)
app.include_router(psych.router)
app.include_router(music.router)

# 圖片只透過 /api/media/{題號} 提供，不直接公開資料夾（檔名常常就是答案）
app.mount("/css", StaticFiles(directory=STATIC_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=STATIC_DIR / "js"), name="js")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}
