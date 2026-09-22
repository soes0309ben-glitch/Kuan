import random

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.data_store import (
    REGION_LABELS,
    find_attraction,
    get_attractions,
    get_itineraries,
    get_itineraries_by_id,
)
from app.db import get_db
from app.dependencies import get_current_user, user_unlocked_itineraries
from app.flight_prices import flight_price_info
from app.models import Purchase, User
from app.news_service import get_travel_news
from app.seasons import current_season_hero
from app.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, user: User | None = Depends(get_current_user)):
    attractions = get_attractions()
    featured = random.sample(attractions, k=min(8, len(attractions))) if attractions else []
    itineraries = get_itineraries()[:4]
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "featured": featured,
            "itineraries": itineraries,
            "season_hero": current_season_hero(),
        },
    )


@router.get("/explore", response_class=HTMLResponse)
def explore(request: Request, q: str = Query(""), user: User | None = Depends(get_current_user)):
    return templates.TemplateResponse(
        request,
        "explore.html",
        {"user": user, "regions": REGION_LABELS, "q": q},
    )


@router.get("/favorites", response_class=HTMLResponse)
def favorites(request: Request, user: User | None = Depends(get_current_user)):
    return templates.TemplateResponse(request, "favorites.html", {"user": user})


@router.get("/guides/beginner", response_class=HTMLResponse)
def guide_beginner(request: Request, user: User | None = Depends(get_current_user)):
    return templates.TemplateResponse(request, "guide_beginner.html", {"user": user})


@router.get("/news", response_class=HTMLResponse)
def news(request: Request, user: User | None = Depends(get_current_user)):
    return templates.TemplateResponse(request, "news.html", {"user": user, "news": get_travel_news()})


@router.get("/itineraries", response_class=HTMLResponse)
def itineraries_list(
    request: Request,
    duration: str = Query(""),
    region: str = Query(""),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = get_itineraries()
    if duration:
        items = [i for i in items if i["duration"] == duration]
    if region:
        items = [i for i in items if i["region"] == region]
    unlocked = user_unlocked_itineraries(db, user)
    return templates.TemplateResponse(
        request,
        "itineraries.html",
        {
            "user": user,
            "itineraries": items,
            "unlocked": unlocked,
            "duration_filter": duration,
            "region_filter": region,
        },
    )


@router.get("/itineraries/{itinerary_id}", response_class=HTMLResponse)
def itinerary_detail(
    itinerary_id: str,
    request: Request,
    unlocked: int = Query(0),
    canceled: int = Query(0),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    itinerary = get_itineraries_by_id().get(itinerary_id)
    if not itinerary:
        return HTMLResponse("找不到這個行程", status_code=404)

    unlocked_ids = user_unlocked_itineraries(db, user)
    has_access = itinerary_id in unlocked_ids

    day_attractions = {}
    for day in itinerary["days"]:
        for aid in day.get("attraction_ids", []):
            if aid not in day_attractions:
                attraction = find_attraction(aid)
                if attraction:
                    day_attractions[aid] = attraction

    return templates.TemplateResponse(
        request,
        "itinerary_detail.html",
        {
            "user": user,
            "itinerary": itinerary,
            "has_access": has_access,
            "day_attractions": day_attractions,
            "just_unlocked": bool(unlocked),
            "canceled": bool(canceled),
            "flight_prices": flight_price_info(itinerary["region"]),
        },
    )


@router.get("/account/purchases", response_class=HTMLResponse)
def my_purchases(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user:
        return templates.TemplateResponse(request, "login.html", {"error": "請先登入"})
    purchases = (
        db.query(Purchase)
        .filter(Purchase.user_id == user.id, Purchase.status == "paid")
        .order_by(Purchase.created_at.desc())
        .all()
    )
    itineraries_by_id = get_itineraries_by_id()
    rows = [
        {"purchase": p, "itinerary": itineraries_by_id.get(p.itinerary_id)} for p in purchases
    ]
    return templates.TemplateResponse(request, "purchases.html", {"user": user, "rows": rows})
