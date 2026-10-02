"""資料表。表名都加 quiz_ 前綴，才能和 japan-travel 共用同一個 Postgres。"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


ACTIVE_SUBSCRIPTION_STATUSES = ("active", "trialing")
DIFFICULTIES = ("easy", "medium", "hard")


class User(Base):
    __tablename__ = "quiz_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    google_sub: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    picture: Mapped[str] = mapped_column(String(500), default="")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subscription_status: Mapped[str] = mapped_column(String(32), default="none")
    subscription_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    attempts: Mapped[list["Attempt"]] = relationship(back_populates="user")

    @property
    def is_subscribed(self) -> bool:
        return self.subscription_status in ACTIVE_SUBSCRIPTION_STATUSES


class Question(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cat: Mapped[str] = mapped_column(String(20), index=True)
    type: Mapped[str] = mapped_column(String(10))  # single / image / short / qa
    difficulty: Mapped[str] = mapped_column(String(10), index=True, default="medium")  # easy / medium / hard
    q: Mapped[str] = mapped_column(Text)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    accept: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    explain: Mapped[str | None] = mapped_column(Text, nullable=True)
    img: Mapped[str | None] = mapped_column(String(100), nullable=True)
    emoji: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Attempt(Base):
    """一個使用者在「主題 × 難度」的唯一一次挑戰。按下開始就建立，不能重來。"""

    __tablename__ = "quiz_attempts"
    __table_args__ = (
        UniqueConstraint("user_id", "category", "difficulty", name="uq_quiz_attempt_user_category_difficulty"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("quiz_users.id"), index=True)
    category: Mapped[str] = mapped_column(String(20))
    difficulty: Mapped[str] = mapped_column(String(10))
    question_ids: Mapped[list] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Float, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="attempts")
    answers: Mapped[list["AttemptAnswer"]] = relationship(back_populates="attempt", cascade="all, delete-orphan")


class AttemptAnswer(Base):
    __tablename__ = "quiz_attempt_answers"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_quiz_answer_once"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("quiz_attempts.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("quiz_questions.id"))
    given: Mapped[str] = mapped_column(Text, default="")
    # 問答題先存 None，等作答者看完參考答案自評後才填分數
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    attempt: Mapped[Attempt] = relationship(back_populates="answers")
