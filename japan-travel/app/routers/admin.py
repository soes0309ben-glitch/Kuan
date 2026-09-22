import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.data_store import TIER_LABELS, get_itineraries_by_id
from app.db import get_db
from app.dependencies import require_admin
from app.models import PageView, Purchase, User
from app.templating import templates

router = APIRouter(prefix="/admin")

_TREND_DAYS = 14


@router.get("", response_class=HTMLResponse)
def dashboard(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    since = datetime.datetime.utcnow() - datetime.timedelta(days=_TREND_DAYS)

    total_users = db.query(func.count(User.id)).scalar() or 0
    total_page_views = db.query(func.count(PageView.id)).scalar() or 0
    total_revenue = (
        db.query(func.coalesce(func.sum(Purchase.amount_twd), 0))
        .filter(Purchase.status == "paid")
        .scalar()
        or 0
    )
    total_orders = db.query(func.count(Purchase.id)).filter(Purchase.status == "paid").scalar() or 0

    def _daily_counts(model, date_col):
        rows = (
            db.query(func.date(date_col), func.count())
            .filter(date_col >= since)
            .group_by(func.date(date_col))
            .all()
        )
        return {day: count for day, count in rows}

    signups_by_day = _daily_counts(User, User.created_at)
    views_by_day = _daily_counts(PageView, PageView.created_at)

    trend = []
    for i in range(_TREND_DAYS - 1, -1, -1):
        day = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
        trend.append(
            {"day": day[5:], "signups": signups_by_day.get(day, 0), "views": views_by_day.get(day, 0)}
        )
    max_views = max((d["views"] for d in trend), default=0) or 1
    max_signups = max((d["signups"] for d in trend), default=0) or 1
    for d in trend:
        d["views_pct"] = round(d["views"] / max_views * 100)
        d["signups_pct"] = round(d["signups"] / max_signups * 100)

    itineraries_by_id = get_itineraries_by_id()
    sales_rows = (
        db.query(Purchase.itinerary_id, Purchase.tier, func.count(), func.sum(Purchase.amount_twd))
        .filter(Purchase.status == "paid")
        .group_by(Purchase.itinerary_id, Purchase.tier)
        .order_by(func.count().desc())
        .all()
    )
    best_sellers = [
        {
            "title": itineraries_by_id.get(itinerary_id, {}).get("title", itinerary_id),
            "tier_label": TIER_LABELS.get(tier, tier),
            "orders": count,
            "revenue": revenue,
        }
        for itinerary_id, tier, count, revenue in sales_rows
    ]

    recent_purchases = (
        db.query(Purchase)
        .filter(Purchase.status == "paid")
        .order_by(Purchase.created_at.desc())
        .limit(10)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "user": admin,
            "total_users": total_users,
            "total_page_views": total_page_views,
            "total_revenue": total_revenue,
            "total_orders": total_orders,
            "trend": trend,
            "best_sellers": best_sellers,
            "recent_purchases": recent_purchases,
            "itineraries_by_id": itineraries_by_id,
            "trend_days": _TREND_DAYS,
        },
    )
