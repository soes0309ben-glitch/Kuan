import secrets

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PageView


def track_page_view(request: Request, db: Session = Depends(get_db)) -> None:
    """Router-level dependency (see main.py) that logs one row per page
    view, keyed by a random per-browser-session id (not tied to login) so
    the admin dashboard can show real visitor/traffic trends.
    """
    try:
        session_key = request.session.get("_pv_key")
        if not session_key:
            session_key = secrets.token_hex(8)
            request.session["_pv_key"] = session_key
        db.add(PageView(path=request.url.path, session_key=session_key))
        db.commit()
    except Exception:
        db.rollback()
