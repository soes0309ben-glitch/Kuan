import logging

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)


def send_notification(subject: str, body: str) -> None:
    """Sends a plain-text notification email to the site owner via Resend's
    HTTP API (https://resend.com — simple REST API, generous free tier).
    No-ops (log only) until RESEND_API_KEY / NOTIFY_EMAIL are configured,
    so nothing breaks before the owner has applied for a key.
    """
    settings = get_settings()
    if not settings.resend_api_key or not settings.notify_email:
        logger.info("Email notification skipped (not configured): %s", subject)
        return

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.notify_from_email or "onboarding@resend.dev",
                "to": [settings.notify_email],
                "subject": subject,
                "text": body,
            },
            timeout=8,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        # Never let a notification failure break the request that triggered it
        # (registration / checkout still succeeded).
        logger.warning("Failed to send notification email %r: %s", subject, exc)


def notify_new_member(email: str) -> None:
    send_notification(
        subject="旅日誌：有新會員註冊",
        body=f"新會員註冊：{email}",
    )


def notify_purchase(*, user_email: str, itinerary_title: str, tier_label: str, amount_twd: int) -> None:
    send_notification(
        subject="旅日誌：有新訂單完成付款",
        body=(
            f"買家：{user_email}\n"
            f"行程：{itinerary_title}\n"
            f"方案：{tier_label}\n"
            f"金額：NT$ {amount_twd}"
        ),
    )
