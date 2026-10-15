"""網頁登入：LINE Login（OAuth 2.1 + OpenID Connect），或 LINE 機器人發的一次性連結。"""

import secrets
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.dependencies import public_base_url, require_json
from app.users import consume_login_token, get_or_create_user

router = APIRouter()

AUTHORIZE_URL = "https://access.line.me/oauth2/v2.1/authorize"
TOKEN_URL = "https://api.line.me/oauth2/v2.1/token"
VERIFY_URL = "https://api.line.me/oauth2/v2.1/verify"


def _redirect_uri(request: Request) -> str:
    return f"{public_base_url(request)}/auth/line/callback"


def _login(request: Request, user_id: int) -> None:
    request.session.clear()
    request.session["uid"] = user_id


@router.get("/auth/line/login")
def line_login(request: Request):
    settings = get_settings()
    if not settings.line_login_enabled:
        raise HTTPException(503, "LINE Login 尚未設定（缺 LINE_LOGIN_CHANNEL_ID / LINE_LOGIN_CHANNEL_SECRET）")
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    request.session["oauth_nonce"] = nonce
    params = {
        "response_type": "code",
        "client_id": settings.line_login_channel_id,
        "redirect_uri": _redirect_uri(request),
        "state": state,
        "nonce": nonce,
        "scope": "openid profile",
        # 登入時順便邀請加官方帳號好友（LINE Login channel 需先在後台連結官方帳號）
        "bot_prompt": "aggressive",
    }
    return RedirectResponse(f"{AUTHORIZE_URL}?{urlencode(params)}", status_code=303)


@router.get("/auth/line/callback")
def line_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    expected = request.session.pop("oauth_state", None)
    nonce = request.session.pop("oauth_nonce", None)
    if error:
        return RedirectResponse("/?login=cancelled", status_code=303)
    if not code or not state or not expected or not secrets.compare_digest(state, expected):
        raise HTTPException(400, "登入驗證失敗，請重新登入")

    settings = get_settings()
    token_res = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect_uri(request),
        "client_id": settings.line_login_channel_id,
        "client_secret": settings.line_login_channel_secret,
    }, timeout=15)
    if token_res.status_code != 200:
        raise HTTPException(400, "無法向 LINE 取得登入憑證，請重試")
    id_token = token_res.json().get("id_token", "")
    # 交給 LINE 驗證 ID token 的簽章、期限、client_id 與 nonce
    verify = requests.post(VERIFY_URL, data={
        "id_token": id_token, "client_id": settings.line_login_channel_id, "nonce": nonce or "",
    }, timeout=15)
    info = verify.json() if verify.status_code == 200 else {}
    if not info.get("sub"):
        raise HTTPException(400, "LINE 登入驗證失敗，請重試")

    user = get_or_create_user(db, info["sub"], info.get("name", ""), info.get("picture", ""))
    db.commit()
    _login(request, user.id)
    return RedirectResponse("/", status_code=303)


@router.get("/auth/magic")
def magic_link(request: Request, token: str = "", db: Session = Depends(get_db)):
    user = consume_login_token(db, token)
    if not user:
        return RedirectResponse("/?login=expired", status_code=303)
    db.commit()
    _login(request, user.id)
    return RedirectResponse("/", status_code=303)


@router.post("/auth/dev-login", dependencies=[Depends(require_json)])
def dev_login(request: Request, db: Session = Depends(get_db)):
    """本機開發用（DEV_LOGIN=true 才開放）：不經 LINE 直接登入一個測試帳號。"""
    if not get_settings().dev_login:
        raise HTTPException(404, "Not Found")
    user = get_or_create_user(db, "Udev000000000000000000000000000000", "開發者")
    db.commit()
    _login(request, user.id)
    return {"ok": True}


@router.post("/auth/logout", dependencies=[Depends(require_json)])
def logout(request: Request):
    request.session.clear()
    return {"ok": True}
