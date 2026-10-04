"""Stripe 月訂閱：Checkout 付款、Customer Portal 管理、webhook 同步訂閱狀態。"""

from datetime import datetime, timezone

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MusicSubscription, User

# Dashboard 中用來辨識這個結帳流程的標籤（後 8 碼為隨機字母）
INTEGRATION_IDENTIFIER = "quiz-bank-monthly-qhzrtwkm"


def client() -> stripe.StripeClient:
    key = get_settings().stripe_secret_key
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY 未設定")
    return stripe.StripeClient(key)


def ensure_customer(db: Session, user: User) -> str:
    if not user.stripe_customer_id:
        customer = client().v1.customers.create({"email": user.email, "name": user.name or None})
        user.stripe_customer_id = customer.id
        db.commit()
    return user.stripe_customer_id


PLANS = {
    # 方案：(Price ID 設定名, 月費設定名, 商品名稱, 付款後回到的頁面)
    "bank": ("stripe_price_id", "monthly_price_twd", "知識大挑戰・題庫總覽月訂閱", "bank"),
    "music": ("stripe_music_price_id", "music_price_twd", "知識大挑戰・音樂品味題庫月訂閱", "music-bank"),
}


def create_checkout_url(db: Session, user: User, base_url: str, plan: str = "bank") -> str:
    settings = get_settings()
    price_key, amount_key, product, view = PLANS[plan]
    if getattr(settings, price_key):
        line_item = {"price": getattr(settings, price_key), "quantity": 1}
    else:
        line_item = {
            "price_data": {
                "currency": "twd",
                # TWD 在 Stripe API 不是零位小數幣別，金額要乘 100
                "unit_amount": getattr(settings, amount_key) * 100,
                "recurring": {"interval": "month"},
                "product_data": {"name": product},
            },
            "quantity": 1,
        }
    session = client().v1.checkout.sessions.create(
        {
            "mode": "subscription",
            "customer": ensure_customer(db, user),
            "line_items": [line_item],
            # 在訂閱上標記方案，webhook 才分得出是知識題庫還是音樂題庫
            "subscription_data": {"metadata": {"plan": plan}},
            "integration_identifier": INTEGRATION_IDENTIFIER,
            "success_url": f"{base_url}/?view={view}&checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{base_url}/?view={view}&checkout=cancelled",
        }
    )
    return session.url


def create_portal_url(user: User, base_url: str, plan: str = "bank") -> str:
    session = client().v1.billing_portal.sessions.create(
        {"customer": user.stripe_customer_id, "return_url": f"{base_url}/?view={PLANS[plan][3]}"}
    )
    return session.url


def _plain(obj) -> dict:
    # Stripe SDK v16 的物件不是 dict，沒有 .get()；統一轉成一般 dict 再處理
    return obj.to_dict() if hasattr(obj, "to_dict") else obj


def _period_end(subscription: dict) -> datetime | None:
    # 新版 API 的計費週期放在訂閱項目上
    items = subscription.get("items", {}).get("data", [])
    ts = items[0].get("current_period_end") if items else None
    return datetime.fromtimestamp(ts, timezone.utc) if ts else None


def apply_subscription(db: Session, subscription) -> User | None:
    """依 Stripe Customer 找到使用者並更新訂閱狀態（以 Stripe 物件關聯為準，不靠 metadata）。"""
    subscription = _plain(subscription)
    customer_id = subscription["customer"]
    user = db.scalar(select(User).where(User.stripe_customer_id == customer_id))
    if not user:
        return None
    if (subscription.get("metadata") or {}).get("plan") == "music":
        sub = db.get(MusicSubscription, user.id) or MusicSubscription(user_id=user.id)
        # 已有另一筆有效的音樂訂閱時，不讓失效的舊訂閱蓋掉
        if not (sub.stripe_subscription_id and sub.stripe_subscription_id != subscription["id"] and sub.active
                and subscription["status"] not in ("active", "trialing")):
            sub.stripe_subscription_id = subscription["id"]
            sub.status = subscription["status"]
            sub.period_end = _period_end(subscription)
            db.add(sub)
            db.commit()
        return user
    # 同一位使用者若有多筆訂閱，只要有一筆有效就保留有效狀態
    if user.stripe_subscription_id and user.stripe_subscription_id != subscription["id"] and user.is_subscribed:
        if subscription["status"] not in ("active", "trialing"):
            return user
    user.stripe_subscription_id = subscription["id"]
    user.subscription_status = subscription["status"]
    user.subscription_period_end = _period_end(subscription)
    db.commit()
    return user


def music_subscribed(db: Session, user: User | None) -> bool:
    sub = db.get(MusicSubscription, user.id) if user else None
    return bool(sub and sub.active)


def sync_customer(db: Session, customer_id: str) -> None:
    """重新向 Stripe 讀取該顧客最新的訂閱（用於 invoice 事件與付款完成後的即時同步）。"""
    subs = client().v1.subscriptions.list({"customer": customer_id, "status": "all", "limit": 10})
    data = sorted((_plain(s) for s in subs.data), key=lambda s: s["status"] in ("active", "trialing"))
    for sub in data:  # 有效的排在最後，最後寫入者勝出
        apply_subscription(db, sub)


SUBSCRIPTION_EVENTS = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.paused",
    "customer.subscription.resumed",
}


def handle_event(db: Session, event) -> None:
    event = _plain(event)
    obj = event["data"]["object"]
    etype = event["type"]
    if etype in SUBSCRIPTION_EVENTS:
        apply_subscription(db, obj)
    elif etype in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        if obj.get("mode") == "subscription" and obj.get("customer"):
            sync_customer(db, obj["customer"])
    elif etype in ("invoice.paid", "invoice.payment_failed"):
        if obj.get("customer"):
            sync_customer(db, obj["customer"])
