"""LINE Messaging API webhook：LINE Developers → Messaging API → Webhook URL 填 {BASE_URL}/line/webhook"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import bot, line_api
from app.db import get_db
from app.models import User
from app.users import get_or_create_user

logger = logging.getLogger(__name__)
router = APIRouter()


def _user_for(db: Session, line_user_id: str, fetch_profile: bool = False):
    user = db.query(User).filter(User.line_user_id == line_user_id).first()
    if user and not fetch_profile:
        return user
    profile = line_api.get_profile(line_user_id)
    return get_or_create_user(db, line_user_id, profile.get("displayName", ""), profile.get("pictureUrl", ""))


@router.post("/line/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    if not line_api.verify_signature(body, request.headers.get("x-line-signature", "")):
        raise HTTPException(400, "簽章驗證失敗")
    try:
        events = json.loads(body).get("events", [])
    except ValueError:
        raise HTTPException(400, "格式錯誤")

    for event in events:
        source = event.get("source", {})
        # 只處理一對一聊天；群組裡不記帳，避免別人的訊息被記進來
        if source.get("type") != "user" or not source.get("userId"):
            continue
        try:
            messages = _handle_event(db, source["userId"], event)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("處理 LINE 事件失敗")
            messages = [line_api.text("😵 系統忙碌中，這則沒有記到，請稍後再試一次。")]
        if messages and event.get("replyToken"):
            line_api.reply(event["replyToken"], messages)
    # LINE 只要求回 200；處理失敗也回 200，避免 LINE 一直重送同一事件
    return {"ok": True}


def _handle_event(db: Session, line_user_id: str, event: dict) -> list[dict]:
    etype = event.get("type")
    if etype == "follow":
        user = _user_for(db, line_user_id, fetch_profile=True)
        user.bot_friend = True
        return bot.welcome_message(user)
    if etype == "unfollow":
        user = db.query(User).filter(User.line_user_id == line_user_id).first()
        if user:
            user.bot_friend = False
            user.reminder_enabled = False
        return []
    user = _user_for(db, line_user_id)
    user.bot_friend = True
    if etype == "message":
        message = event.get("message", {})
        if message.get("type") == "text":
            return bot.handle_text(db, user, message.get("text", ""))
        if message.get("type") == "sticker":
            return [line_api.text("收到貼圖 😆 要記帳請傳「內容 金額」，例如「午餐 120」。", bot.MAIN_QUICK)]
        return [line_api.text("目前只看得懂文字喔！例如「午餐 120」。", bot.MAIN_QUICK)]
    if etype == "postback":
        return bot.handle_postback(db, user, event.get("postback", {}).get("data", ""))
    return []
