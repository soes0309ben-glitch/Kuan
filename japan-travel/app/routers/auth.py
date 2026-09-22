import re

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.csrf import verify_csrf
from app.db import get_db
from app.dependencies import get_current_user
from app.email_service import notify_new_member
from app.models import User
from app.security import hash_password, verify_password
from app.templating import templates

router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.get("/register")
def register_page(request: Request, user: User | None = Depends(get_current_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "register.html", {"error": None})


@router.post("/register")
def register_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    csrf_token: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf_token)

    email = email.strip().lower()
    error = None
    if not EMAIL_RE.match(email):
        error = "請輸入有效的電子郵件地址"
    elif len(password) < 8:
        error = "密碼至少需要 8 個字元"
    elif db.query(User).filter(User.email == email).first():
        error = "這個電子郵件已經註冊過了，請直接登入"

    if error:
        return templates.TemplateResponse(request, "register.html", {"error": error}, status_code=400)

    password_hash, salt = hash_password(password)
    user = User(email=email, password_hash=password_hash, password_salt=salt)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two concurrent registrations for the same email raced past the
        # SELECT check above; the unique constraint is the real guard.
        db.rollback()
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "這個電子郵件已經註冊過了，請直接登入"},
            status_code=400,
        )
    db.refresh(user)
    background_tasks.add_task(notify_new_member, user.email)

    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@router.get("/login")
def login_page(request: Request, user: User | None = Depends(get_current_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(
    request: Request,
    csrf_token: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf_token)

    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash, user.password_salt):
        return templates.TemplateResponse(
            request, "login.html", {"error": "電子郵件或密碼不正確"}, status_code=400
        )

    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/", status_code=303)
