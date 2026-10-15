"""排程推播：由外部排程（Render Cron Job、GitHub Actions、cron-job.org…）每小時呼叫一次。

    curl -X POST -H "X-Cron-Token: $CRON_TOKEN" $BASE_URL/cron/hourly

推播會用到 LINE 官方帳號的每月免費訊息額度，所以只推給有開啟提醒的人，且同一天只推一次。
"""

import datetime
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import bot, line_api
from app.config import get_settings
from app.db import get_db
from app.ledger import period_bounds, period_key, shift_key
from app.models import ReminderLog, Transaction, User

router = APIRouter(prefix="/cron")


def require_cron_token(x_cron_token: str = Header("")) -> None:
    expected = get_settings().cron_token
    if not expected or not secrets.compare_digest(expected, x_cron_token):
        raise HTTPException(403, "排程金鑰錯誤")


def _claim(db: Session, user: User, kind: str, day: datetime.date) -> bool:
    """搶到這個（使用者, 種類, 日期）的推播權才推；排程重跑或同時跑兩次都不會重複。"""
    try:
        with db.begin_nested():
            db.add(ReminderLog(user_id=user.id, kind=kind, day=day))
        return True
    except IntegrityError:
        return False


@router.post("/hourly", dependencies=[Depends(require_cron_token)])
def hourly(db: Session = Depends(get_db)):
    now = datetime.datetime.now(get_settings().tz)
    day = now.date()
    sent = {"reminder": 0, "monthly_report": 0}

    # 每日提醒：到了使用者設定的整點，當天還沒記帳就提醒
    users = db.query(User).filter(User.bot_friend.is_(True), User.reminder_enabled.is_(True),
                                  User.reminder_hour == now.hour).all()
    for user in users:
        recorded = db.query(Transaction.id).filter(Transaction.user_id == user.id,
                                                   Transaction.occurred_on == day).first()
        if recorded or not _claim(db, user, "reminder", day):
            continue
        if line_api.push(user.line_user_id, [line_api.text(
            "⏰ 今天還沒記帳喔！\n直接傳「午餐 120」就能記一筆；今天沒花錢也可以忽略這則提醒 😊", bot.MAIN_QUICK)]):
            sent["reminder"] += 1

    # 月報：新的一期第一天早上 9 點，推上一期的統計給有開提醒的人
    if now.hour == 9:
        for user in db.query(User).filter(User.bot_friend.is_(True), User.reminder_enabled.is_(True)).all():
            key = period_key(user, day)
            start, _ = period_bounds(user, key)
            if start != day or not _claim(db, user, "monthly_report", day):
                continue
            prev = shift_key(key, -1)
            messages = bot.summary_message(db, user, f"📊 {int(prev[5:])} 月月報", *period_bounds(user, prev),
                                           with_budget=True)
            if line_api.push(user.line_user_id, messages):
                sent["monthly_report"] += 1
    db.commit()
    return {"ok": True, "sent": sent}
