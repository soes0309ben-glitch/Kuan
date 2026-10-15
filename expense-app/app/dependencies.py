from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    return db.get(User, uid) if uid else None


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if not user:
        raise HTTPException(401, "請先用 LINE 登入")
    return user


def require_json(request: Request) -> None:
    """改變資料的 API 只接受 JSON。跨站表單送不出 JSON，搭配 SameSite=Lax cookie 可擋 CSRF。"""
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "請以 JSON 送出")


def public_base_url(request: Request) -> str:
    """對外網址（LINE Login 回呼用）。BASE_URL 的主機與實際連線相同才採用，否則用實際網址。"""
    host = request.headers.get("host", "")
    configured = get_settings().base_url.strip().rstrip("/")
    if host and urlsplit(configured).netloc == host:
        return configured
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    return f"{proto}://{host}" if host else configured
