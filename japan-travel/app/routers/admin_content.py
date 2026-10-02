import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.csrf import verify_csrf
from app.data_store import (
    DURATION_LABELS,
    REGION_LABELS,
    TIER_LABELS,
    delete_content_override,
    find_attraction,
    find_itinerary,
    get_attractions,
    get_itineraries,
    save_content_override,
)
from app.db import get_db
from app.dependencies import require_admin
from app.models import User
from app.templating import templates

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

_DURATION_NIGHTS = {key: int(re.match(r"\d+d(\d+)n", key).group(1)) for key in DURATION_LABELS}
_MAX_DAYS = 7


# ---------------------------------------------------------------------------
# Attractions
# ---------------------------------------------------------------------------


@router.get("/attractions", response_class=HTMLResponse)
def attractions_list(request: Request, admin: User = Depends(require_admin)):
    items = sorted(get_attractions(), key=lambda a: a["id"])
    return templates.TemplateResponse(
        request, "admin/attractions_list.html", {"user": admin, "attractions": items}
    )


@router.get("/attractions/new", response_class=HTMLResponse)
def attraction_new_form(request: Request, admin: User = Depends(require_admin)):
    return templates.TemplateResponse(
        request,
        "admin/attraction_form.html",
        {"user": admin, "attraction": None, "is_new": True, "region_labels": REGION_LABELS},
    )


@router.get("/attractions/{attraction_id}/edit", response_class=HTMLResponse)
def attraction_edit_form(
    attraction_id: str, request: Request, admin: User = Depends(require_admin)
):
    attraction = find_attraction(attraction_id)
    if not attraction:
        raise HTTPException(404, "找不到這個景點")
    return templates.TemplateResponse(
        request,
        "admin/attraction_form.html",
        {"user": admin, "attraction": attraction, "is_new": False, "region_labels": REGION_LABELS},
    )


@router.post("/attractions/new")
def attraction_create(
    request: Request,
    csrf_token: str = Form(...),
    id: str = Form(...),
    name_zh: str = Form(...),
    name_ja: str = Form(""),
    region: str = Form(...),
    prefecture: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    description: str = Form(""),
    image_query: str = Form(""),
    official_url: str = Form(""),
    access_from: str = Form(""),
    access_method: str = Form(""),
    access_duration_min: str = Form(""),
    access_cost_jpy: str = Form(""),
    self_drive_note: str = Form(""),
    visit_duration_min: str = Form(""),
    entry_fee_jpy: str = Form(""),
    best_season: str = Form(""),
    is_remote_island: bool = Form(False),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf_token)
    item_id = id.strip()
    if not item_id:
        raise HTTPException(400, "景點 ID 不能空白")
    if find_attraction(item_id):
        raise HTTPException(400, "這個景點 ID 已經存在")
    data = _attraction_payload(
        item_id, name_zh, name_ja, region, prefecture, category, tags, description, image_query,
        official_url, access_from, access_method, access_duration_min, access_cost_jpy,
        self_drive_note, visit_duration_min, entry_fee_jpy, best_season, is_remote_island,
    )
    save_content_override(db, "attraction", item_id, data)
    return RedirectResponse("/admin/attractions", status_code=303)


@router.post("/attractions/{attraction_id}/edit")
def attraction_update(
    attraction_id: str,
    request: Request,
    csrf_token: str = Form(...),
    name_zh: str = Form(...),
    name_ja: str = Form(""),
    region: str = Form(...),
    prefecture: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    description: str = Form(""),
    image_query: str = Form(""),
    official_url: str = Form(""),
    access_from: str = Form(""),
    access_method: str = Form(""),
    access_duration_min: str = Form(""),
    access_cost_jpy: str = Form(""),
    self_drive_note: str = Form(""),
    visit_duration_min: str = Form(""),
    entry_fee_jpy: str = Form(""),
    best_season: str = Form(""),
    is_remote_island: bool = Form(False),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf_token)
    if not find_attraction(attraction_id):
        raise HTTPException(404, "找不到這個景點")
    data = _attraction_payload(
        attraction_id, name_zh, name_ja, region, prefecture, category, tags, description,
        image_query, official_url, access_from, access_method, access_duration_min,
        access_cost_jpy, self_drive_note, visit_duration_min, entry_fee_jpy, best_season,
        is_remote_island,
    )
    save_content_override(db, "attraction", attraction_id, data)
    return RedirectResponse("/admin/attractions", status_code=303)


@router.post("/attractions/{attraction_id}/delete")
def attraction_delete(
    attraction_id: str,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf_token)
    delete_content_override(db, "attraction", attraction_id)
    return RedirectResponse("/admin/attractions", status_code=303)


def _attraction_payload(
    item_id, name_zh, name_ja, region, prefecture, category, tags, description, image_query,
    official_url, access_from, access_method, access_duration_min, access_cost_jpy,
    self_drive_note, visit_duration_min, entry_fee_jpy, best_season, is_remote_island,
) -> dict:
    data = {
        "id": item_id,
        "name_zh": name_zh.strip(),
        "name_ja": name_ja.strip(),
        "region": region,
        "prefecture": prefecture.strip(),
        "category": category.strip() or "attraction",
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "description": description.strip(),
        "image_query": image_query.strip() or name_zh.strip(),
        "official_url": official_url.strip(),
        "self_drive_note": self_drive_note.strip(),
        "best_season": best_season.strip(),
        "is_remote_island": is_remote_island,
    }
    if visit_duration_min.strip():
        data["visit_duration_min"] = int(visit_duration_min)
    if entry_fee_jpy.strip():
        data["entry_fee_jpy"] = int(entry_fee_jpy)
    if access_from.strip() or access_method.strip():
        data["access"] = {
            "from": access_from.strip(),
            "method": access_method.strip(),
            "duration_min": int(access_duration_min) if access_duration_min.strip() else 0,
            "cost_jpy": int(access_cost_jpy) if access_cost_jpy.strip() else 0,
        }
    return data


# ---------------------------------------------------------------------------
# Itineraries
# ---------------------------------------------------------------------------


@router.get("/itineraries", response_class=HTMLResponse)
def admin_itineraries_list(request: Request, admin: User = Depends(require_admin)):
    items = sorted(get_itineraries(), key=lambda i: i["id"])
    return templates.TemplateResponse(
        request, "admin/itineraries_list.html", {"user": admin, "itineraries": items}
    )


@router.get("/itineraries/new", response_class=HTMLResponse)
def itinerary_new_form(request: Request, admin: User = Depends(require_admin)):
    return templates.TemplateResponse(
        request,
        "admin/itinerary_form.html",
        {
            "user": admin,
            "itinerary": None,
            "days_by_number": {},
            "is_new": True,
            "region_labels": REGION_LABELS,
            "duration_labels": DURATION_LABELS,
            "tier_labels": TIER_LABELS,
            "day_range": range(1, _MAX_DAYS + 1),
            "attraction_reference": sorted(get_attractions(), key=lambda a: a["id"]),
        },
    )


@router.get("/itineraries/{itinerary_id}/edit", response_class=HTMLResponse)
def itinerary_edit_form(
    itinerary_id: str, request: Request, admin: User = Depends(require_admin)
):
    itinerary = find_itinerary(itinerary_id)
    if not itinerary:
        raise HTTPException(404, "找不到這個行程")
    return templates.TemplateResponse(
        request,
        "admin/itinerary_form.html",
        {
            "user": admin,
            "itinerary": itinerary,
            "days_by_number": {d["day"]: d for d in itinerary.get("days", [])},
            "is_new": False,
            "region_labels": REGION_LABELS,
            "duration_labels": DURATION_LABELS,
            "tier_labels": TIER_LABELS,
            "day_range": range(1, _MAX_DAYS + 1),
            "attraction_reference": sorted(get_attractions(), key=lambda a: a["id"]),
        },
    )


@router.post("/itineraries/new")
async def itinerary_create(
    request: Request, id: str = Form(...), db: Session = Depends(get_db)
):
    form = await request.form()
    verify_csrf(request, form.get("csrf_token", ""))
    item_id = id.strip()
    if not item_id:
        raise HTTPException(400, "行程 ID 不能空白")
    if find_itinerary(item_id):
        raise HTTPException(400, "這個行程 ID 已經存在")
    data = _itinerary_payload(item_id, form)
    save_content_override(db, "itinerary", item_id, data)
    return RedirectResponse("/admin/itineraries", status_code=303)


@router.post("/itineraries/{itinerary_id}/edit")
async def itinerary_update(itinerary_id: str, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    verify_csrf(request, form.get("csrf_token", ""))
    if not find_itinerary(itinerary_id):
        raise HTTPException(404, "找不到這個行程")
    data = _itinerary_payload(itinerary_id, form)
    save_content_override(db, "itinerary", itinerary_id, data)
    return RedirectResponse("/admin/itineraries", status_code=303)


@router.post("/itineraries/{itinerary_id}/delete")
def itinerary_delete(
    itinerary_id: str,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf_token)
    delete_content_override(db, "itinerary", itinerary_id)
    return RedirectResponse("/admin/itineraries", status_code=303)


def _itinerary_payload(item_id: str, form) -> dict:
    duration = form.get("duration", "3d2n")
    days = []
    for day_num in range(1, _MAX_DAYS + 1):
        title = (form.get(f"day_{day_num}_title") or "").strip()
        activities = (form.get(f"day_{day_num}_activities") or "").strip()
        if not title and not activities:
            continue
        attraction_ids = [
            a.strip() for a in (form.get(f"day_{day_num}_attraction_ids") or "").split(",") if a.strip()
        ]
        cost = (form.get(f"day_{day_num}_cost") or "").strip()
        days.append(
            {
                "day": day_num,
                "title": title,
                "attraction_ids": attraction_ids,
                "activities": activities,
                "transport_notes": (form.get(f"day_{day_num}_transport_notes") or "").strip(),
                "daily_cost_estimate_jpy": int(cost) if cost else 0,
            }
        )

    unlock_price_twd = {}
    accommodation_tiers = {}
    for tier in TIER_LABELS:
        price = (form.get(f"price_{tier}") or "").strip()
        unlock_price_twd[tier] = int(price) if price else 0
        hint = (form.get(f"tier_hint_{tier}") or "").strip()
        night_price = (form.get(f"tier_price_jpy_{tier}") or "").strip()
        accommodation_tiers[tier] = {
            "style_hint": hint,
            "price_per_night_jpy": int(night_price) if night_price else 0,
        }

    return {
        "id": item_id,
        "title": (form.get("title") or "").strip(),
        "duration": duration,
        "nights": _DURATION_NIGHTS.get(duration, 1),
        "region": form.get("region", ""),
        "summary": (form.get("summary") or "").strip(),
        "days": days,
        "self_drive_route": {
            "recommended": form.get("self_drive_recommended") == "on",
            "route_note": (form.get("self_drive_route_note") or "").strip(),
        },
        "packing_notes": (form.get("packing_notes") or "").strip(),
        "accommodation_tiers": accommodation_tiers,
        "unlock_price_twd": unlock_price_twd,
    }
