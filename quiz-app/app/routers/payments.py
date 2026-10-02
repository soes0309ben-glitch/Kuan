import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import billing
from app.config import get_settings
from app.db import get_db
from app.dependencies import public_base_url, require_json, require_user
from app.models import User

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_stripe() -> None:
    if not get_settings().stripe_secret_key:
        raise HTTPException(503, "金流尚未設定完成（缺 STRIPE_SECRET_KEY）")


@router.post("/api/billing/checkout", dependencies=[Depends(require_json)])
def checkout(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    _require_stripe()
    if user.is_subscribed:
        raise HTTPException(409, "你已經是訂閱會員了")
    try:
        return {"url": billing.create_checkout_url(db, user, public_base_url(request))}
    except stripe.StripeError:
        logger.exception("建立 Checkout Session 失敗")
        raise HTTPException(502, "暫時無法連線到付款服務，請稍後再試")


@router.post("/api/billing/portal", dependencies=[Depends(require_json)])
def portal(request: Request, user: User = Depends(require_user)):
    _require_stripe()
    if not user.stripe_customer_id:
        raise HTTPException(400, "你還沒有訂閱紀錄")
    try:
        return {"url": billing.create_portal_url(user, public_base_url(request))}
    except stripe.StripeError:
        logger.exception("建立 Customer Portal 失敗")
        raise HTTPException(502, "暫時無法開啟訂閱管理，請稍後再試")


class SyncBody(BaseModel):
    session_id: str


@router.post("/api/billing/sync", dependencies=[Depends(require_json)])
def sync_after_checkout(body: SyncBody, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """付款完成導回網站時立即同步一次，不必等 webhook；正式的狀態更新仍以 webhook 為主。"""
    _require_stripe()
    try:
        session = billing.client().v1.checkout.sessions.retrieve(body.session_id)
    except stripe.StripeError:
        raise HTTPException(400, "找不到這筆付款")
    if session.customer != user.stripe_customer_id:
        raise HTTPException(403, "這筆付款不屬於目前登入的帳號")
    billing.sync_customer(db, session.customer)
    db.refresh(user)
    return {"subscribed": user.is_subscribed}


@router.post("/stripe/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    payload = await request.body()
    try:
        event = billing.client().construct_event(
            payload, request.headers.get("stripe-signature"), settings.stripe_webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError, RuntimeError):
        raise HTTPException(400, "webhook 驗證失敗")
    # 處理時會呼叫 Stripe API 與資料庫，放到執行緒池以免卡住事件迴圈
    await run_in_threadpool(billing.handle_event, db, event)
    return {"received": True}
