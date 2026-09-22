from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Purchase, User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, user_id)


def require_admin(user: User | None = Depends(get_current_user)) -> User:
    settings = get_settings()
    if not user or user.email.lower() not in settings.admin_email_set:
        # 404 (not 403) so /admin doesn't even reveal it exists to non-admins.
        raise HTTPException(404, "找不到這個頁面")
    return user


def user_unlocked_itineraries(db: Session, user: User | None) -> set[str]:
    if not user:
        return set()
    rows = (
        db.query(Purchase.itinerary_id)
        .filter(Purchase.user_id == user.id, Purchase.status == "paid")
        .distinct()
        .all()
    )
    return {r[0] for r in rows}
