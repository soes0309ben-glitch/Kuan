import logging

import stripe
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.csrf import verify_csrf
from app.data_store import TIER_LABELS, find_itinerary
from app.db import get_db
from app.dependencies import get_current_user
from app.email_service import notify_purchase
from app.models import Purchase, User
from app.stripe_service import (
    construct_webhook_event,
    create_checkout_session,
    retrieve_checkout_session,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/itineraries/{itinerary_id}/checkout")
def start_checkout(
    itinerary_id: str,
    request: Request,
    csrf_token: str = Form(...),
    tier: str = Form(...),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse(f"/login?next=/itineraries/{itinerary_id}", status_code=303)

    verify_csrf(request, csrf_token)

    itinerary = find_itinerary(itinerary_id)
    if not itinerary:
        raise HTTPException(404, "找不到這個行程")
    if tier not in itinerary["unlock_price_twd"]:
        raise HTTPException(400, "住宿方案不存在")

    existing = (
        db.query(Purchase)
        .filter(
            Purchase.user_id == user.id,
            Purchase.itinerary_id == itinerary_id,
            Purchase.tier == tier,
            Purchase.status.in_(("pending", "paid")),
        )
        .order_by(Purchase.created_at.desc())
        .first()
    )
    if existing and existing.status == "paid":
        # Already bought this plan/tier — don't charge again.
        return RedirectResponse(f"/itineraries/{itinerary_id}?unlocked=1", status_code=303)

    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(
            503, "金流尚未設定完成，請管理者於 .env 補上 STRIPE_SECRET_KEY 後再試一次"
        )

    if existing and existing.status == "pending":
        try:
            stripe_session = retrieve_checkout_session(existing.stripe_session_id)
        except stripe.StripeError:
            stripe_session = None
        if stripe_session is not None and stripe_session.status == "open":
            # Resume the still-open Checkout Session instead of double-charging.
            return RedirectResponse(stripe_session.url, status_code=303)

    amount_twd = itinerary["unlock_price_twd"][tier]
    try:
        stripe_session = create_checkout_session(
            itinerary_id=itinerary_id,
            itinerary_title=itinerary["title"],
            tier=tier,
            amount_twd=amount_twd,
            user_email=user.email,
        )
    except stripe.StripeError as exc:
        logger.warning("Stripe checkout session creation failed: %s", exc)
        raise HTTPException(503, "金流服務暫時無法使用，請稍後再試一次") from exc

    purchase = Purchase(
        user_id=user.id,
        itinerary_id=itinerary_id,
        tier=tier,
        amount_twd=amount_twd,
        stripe_session_id=stripe_session.id,
        status="pending",
    )
    db.add(purchase)
    db.commit()

    return RedirectResponse(stripe_session.url, status_code=303)


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = construct_webhook_event(payload, sig_header)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(400, f"Webhook 驗證失敗: {exc}") from exc

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        purchase = (
            db.query(Purchase).filter(Purchase.stripe_session_id == session_obj["id"]).first()
        )
        if purchase:
            if session_obj.get("payment_status") != "paid":
                logger.warning(
                    "checkout.session.completed for %s but payment_status=%s — not unlocking",
                    session_obj["id"],
                    session_obj.get("payment_status"),
                )
            elif session_obj.get("amount_total") != purchase.amount_twd * 100:
                logger.warning(
                    "Amount mismatch for session %s: stripe=%s expected=%s — not unlocking",
                    session_obj["id"],
                    session_obj.get("amount_total"),
                    purchase.amount_twd * 100,
                )
            else:
                purchase.status = "paid"
                db.commit()
                buyer = db.get(User, purchase.user_id)
                itinerary = find_itinerary(purchase.itinerary_id)
                if buyer and itinerary:
                    background_tasks.add_task(
                        notify_purchase,
                        user_email=buyer.email,
                        itinerary_title=itinerary["title"],
                        tier_label=TIER_LABELS.get(purchase.tier, purchase.tier),
                        amount_twd=purchase.amount_twd,
                    )

    return {"received": True}
