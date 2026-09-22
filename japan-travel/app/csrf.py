import secrets

from fastapi import HTTPException, Request

_SESSION_KEY = "csrf_token"


def get_csrf_token(request: Request) -> str:
    token = request.session.get(_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[_SESSION_KEY] = token
    return token


def verify_csrf(request: Request, submitted_token: str) -> None:
    expected = request.session.get(_SESSION_KEY)
    if not expected or not secrets.compare_digest(expected, submitted_token or ""):
        raise HTTPException(400, "表單已過期或驗證失敗，請重新整理頁面再試一次")
