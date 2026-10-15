import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

EXPENSE = "expense"
INCOME = "income"


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # LINE userId（U 開頭 33 字元）。Messaging API 與 LINE Login 在同一 Provider 下會是同一個值
    line_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    picture_url: Mapped[str] = mapped_column(String(500), default="")
    # 是否已加官方帳號好友（封鎖後 LINE 會送 unfollow，就不再推播）
    bot_friend: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_hour: Mapped[int] = mapped_column(Integer, default=21)
    # 月結日：1 表示自然月；25 表示每月 25 日起算（配合發薪日）
    month_start_day: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)

    categories: Mapped[list["Category"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "kind", "name", name="uq_category_user_kind_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    icon: Mapped[str] = mapped_column(String(16), default="")
    # 逗號分隔的關鍵字，LINE 訊息內容含這些字就自動歸到這個分類
    keywords: Mapped[str] = mapped_column(String(1000), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="categories")

    @property
    def keyword_list(self) -> list[str]:
        return [k.strip() for k in self.keywords.split(",") if k.strip()]


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    # 金額以「元」為單位的整數（新台幣不用小數）
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    note: Mapped[str] = mapped_column(String(200), default="")
    occurred_on: Mapped[datetime.date] = mapped_column(Date, index=True, nullable=False)
    # line / web：LINE 的「復原」只撤銷從 LINE 記的最後一筆
    source: Mapped[str] = mapped_column(String(10), default="web")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, index=True)

    category: Mapped["Category"] = relationship()


class Budget(Base):
    """每月預算。category_id 為空代表「總預算」。"""

    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("user_id", "category_id", name="uq_budget_user_category"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)


class LoginToken(Base):
    """LINE 機器人發出的一次性網頁登入連結（只存雜湊，10 分鐘內有效）。"""

    __tablename__ = "login_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class ReminderLog(Base):
    """記錄每天已推播過提醒的使用者，排程重跑也不會重複推。"""

    __tablename__ = "reminder_logs"
    __table_args__ = (UniqueConstraint("user_id", "kind", "day", name="uq_reminder_user_kind_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    day: Mapped[datetime.date] = mapped_column(Date, nullable=False)
