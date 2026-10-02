"""Google 登入（OAuth 2.0 授權碼流程）。"""

import secrets
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.dependencies import require_json
from app.models import User

router = APIRouter()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _redirect_uri() -> str:
    return f"{get_settings().base_url}/auth/google/callback"


def _safe_next(path: str | None) -> str:
    # 只允許站內路徑，避免被當成跳轉到外站的跳板
    return path if path and path.startswith("/") and not path.startswith("//") else "/"


@router.get("/auth/google/login")
def google_login(request: Request, next: str | None = None):
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(503, "Google 登入尚未設定（缺 GOOGLE_CLIENT_ID）")
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    request.session["oauth_next"] = _safe_next(next)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=303)


@router.get("/auth/google/callback")
def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    expected = request.session.pop("oauth_state", None)
    next_path = request.session.pop("oauth_next", "/")
    if error:
        return RedirectResponse("/?login=cancelled", status_code=303)
    if not code or not state or not expected or not secrets.compare_digest(state, expected):
        raise HTTPException(400, "登入驗證失敗，請重新登入")

    settings = get_settings()
    token_res = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": _redirect_uri(),
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    if token_res.status_code != 200:
        raise HTTPException(400, "無法向 Google 取得登入憑證，請重試")
    access_token = token_res.json()["access_token"]
    info = requests.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=15).json()
    if not info.get("sub") or not info.get("email") or not info.get("email_verified"):
        raise HTTPException(400, "這個 Google 帳號沒有已驗證的 Email")

    user = db.scalar(select(User).where(User.google_sub == info["sub"]))
    if not user:
        user = User(google_sub=info["sub"], email=info["email"])
        db.add(user)
    user.email = info["email"]
    user.name = info.get("name", "")
    user.picture = info.get("picture", "")
    db.commit()

    request.session.clear()
    request.session["uid"] = user.id
    return RedirectResponse(next_path, status_code=303)


@router.post("/auth/logout", dependencies=[Depends(require_json)])
def logout(request: Request):
    request.session.clear()
    return {"ok": True}
