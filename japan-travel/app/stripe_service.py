import stripe

from app.config import get_settings
from app.data_store import TIER_LABELS


def _client() -> None:
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key


def create_checkout_session(
    *, itinerary_id: str, itinerary_title: str, tier: str, amount_twd: int, user_email: str
) -> stripe.checkout.Session:
    _client()
    settings = get_settings()
    return stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        customer_email=user_email,
        line_items=[
            {
                "price_data": {
                    "currency": "twd",
                    # TWD is NOT a zero-decimal currency in Stripe's API (unlike JPY),
                    # so unit_amount must be in the smallest unit (x100).
                    "unit_amount": amount_twd * 100,
                    "product_data": {
                        "name": f"{itinerary_title}（{TIER_LABELS.get(tier, tier)}住宿方案）",
                        "description": "解鎖完整每日行程、交通與住宿報價規劃書",
                    },
                },
                "quantity": 1,
            }
        ],
        metadata={"itinerary_id": itinerary_id, "tier": tier, "user_email": user_email},
        success_url=f"{settings.base_url}/itineraries/{itinerary_id}?unlocked=1&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.base_url}/itineraries/{itinerary_id}?canceled=1",
    )


def retrieve_checkout_session(session_id: str) -> stripe.checkout.Session:
    _client()
    return stripe.checkout.Session.retrieve(session_id)


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    settings = get_settings()
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
