"""LINE Messaging API 的薄包裝：簽章驗證、回覆、推播、取得個人資料。"""

import base64
import hashlib
import hmac
import logging

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)

API = "https://api.line.me/v2/bot"


def verify_signature(body: bytes, signature: str) -> bool:
    secret = get_settings().line_channel_secret
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def _headers() -> dict:
    return {"Authorization": f"Bearer {get_settings().line_channel_access_token}", "Content-Type": "application/json"}


def _post(path: str, payload: dict) -> bool:
    if not get_settings().line_channel_access_token:
        logger.warning("LINE_CHANNEL_ACCESS_TOKEN 未設定，略過 %s", path)
        return False
    try:
        res = requests.post(f"{API}{path}", json=payload, headers=_headers(), timeout=10)
    except requests.RequestException:
        logger.exception("呼叫 LINE API %s 失敗", path)
        return False
    if res.status_code != 200:
        logger.warning("LINE API %s 回應 %s：%s", path, res.status_code, res.text[:300])
    return res.status_code == 200


def reply(reply_token: str, messages: list[dict]) -> bool:
    # 回覆一次最多 5 則訊息；回覆不計入每月推播額度
    return _post("/message/reply", {"replyToken": reply_token, "messages": messages[:5]})


def push(line_user_id: str, messages: list[dict]) -> bool:
    return _post("/message/push", {"to": line_user_id, "messages": messages[:5]})


def get_profile(line_user_id: str) -> dict:
    if not get_settings().line_channel_access_token:
        return {}
    try:
        res = requests.get(f"{API}/profile/{line_user_id}", headers=_headers(), timeout=10)
        return res.json() if res.status_code == 200 else {}
    except (requests.RequestException, ValueError):
        return {}


# ---------- 訊息組裝 ----------

def text(message: str, quick_replies: list[dict] | None = None) -> dict:
    msg = {"type": "text", "text": message[:5000]}
    if quick_replies:
        msg["quickReply"] = {"items": quick_replies[:13]}
    return msg


def qr_message(label: str, message: str | None = None) -> dict:
    return {"type": "action", "action": {"type": "message", "label": label[:20], "text": message or label}}


def qr_postback(label: str, data: str, display: str | None = None) -> dict:
    action = {"type": "postback", "label": label[:20], "data": data}
    if display:
        action["displayText"] = display
    return {"type": "action", "action": action}


def flex(alt_text: str, contents: dict, quick_replies: list[dict] | None = None) -> dict:
    msg = {"type": "flex", "altText": alt_text[:400], "contents": contents}
    if quick_replies:
        msg["quickReply"] = {"items": quick_replies[:13]}
    return msg
