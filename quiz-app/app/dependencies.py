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
