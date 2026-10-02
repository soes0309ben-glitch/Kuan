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
        raise HTTPException(401, "請先用 Google 帳號登入")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.email.lower() not in get_settings().admin_email_set:
        raise HTTPException(403, "需要管理者權限")
    return user


def require_json(request: Request) -> None:
    """改變資料的 API 只接受 JSON。跨站表單送不出 JSON，搭配 SameSite=Lax cookie 可擋 CSRF。"""
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "請以 JSON 送出")


def public_base_url(request: Request) -> str:
    """對外網址（Google 回呼、Stripe 付款後跳回用）。

    BASE_URL 與實際網址的主機相同才採用；填錯（例如多貼了一段）時，改用使用者實際連進來的網址，
    避免 Google 登入出現 redirect_uri_mismatch。Render 在前端代理 HTTPS，所以協定看 X-Forwarded-Proto。
    """
    host = request.headers.get("host", "")
    configured = get_settings().base_url.strip().rstrip("/")
    if host and urlsplit(configured).netloc == host:
        return configured
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    return f"{proto}://{host}" if host else configured
