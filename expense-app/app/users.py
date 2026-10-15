import datetime
import hashlib
import secrets

from sqlalchemy.orm import Session

from app.categories import ensure_default_categories
from app.config import get_settings
from app.models import LoginToken, User, utcnow

LOGIN_LINK_TTL = datetime.timedelta(minutes=10)


def get_or_create_user(db: Session, line_user_id: str, display_name: str = "", picture_url: str = "") -> User:
    user = db.query(User).filter(User.line_user_id == line_user_id).first()
    if not user:
        user = User(line_user_id=line_user_id, display_name=display_name, picture_url=picture_url)
        db.add(user)
        db.flush()
        ensure_default_categories(db, user)
    else:
        if display_name:
            user.display_name = display_name
        if picture_url:
            user.picture_url = picture_url
    return user


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_login_link(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(LoginToken(user_id=user.id, token_hash=_hash(token), expires_at=utcnow() + LOGIN_LINK_TTL))
    # 順手清掉過期的連結
    db.query(LoginToken).filter(LoginToken.expires_at < utcnow()).delete()
    return f"{get_settings().base_url.rstrip('/')}/auth/magic?token={token}"


def consume_login_token(db: Session, token: str) -> User | None:
    row = db.query(LoginToken).filter(LoginToken.token_hash == _hash(token or "")).first()
    if not row or row.used or row.expires_at < utcnow():
        return None
    row.used = True
    return db.get(User, row.user_id)
