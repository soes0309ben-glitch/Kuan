"""資料表。表名都加 quiz_ 前綴，才能和 japan-travel 共用同一個 Postgres。"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
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


class Profile(Base):
    """使用者自訂的外觀：暱稱、頭像、頭像框、主題色。獨立成一張表，不必改動既有的 quiz_users。"""

    __tablename__ = "quiz_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("quiz_users.id"), primary_key=True)
    nickname: Mapped[str] = mapped_column(String(30), default="")
    avatar_type: Mapped[str] = mapped_column(String(10), default="google")  # google / emoji / upload
    avatar_emoji: Mapped[str] = mapped_column(String(16), default="")
    avatar_mime: Mapped[str] = mapped_column(String(20), default="")
    avatar_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    frame: Mapped[str] = mapped_column(String(20), default="none")
    color: Mapped[str] = mapped_column(String(20), default="pink")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Team(Base):
    """組隊挑戰：最多 3 人答同一組題目，各自作答、隊內排名。不受個人「只能挑戰一次」限制。"""

    __tablename__ = "quiz_teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("quiz_users.id"))
    category: Mapped[str] = mapped_column(String(20))
    difficulty: Mapped[str] = mapped_column(String(10))
    question_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    members: Mapped[list["TeamMember"]] = relationship(
        back_populates="team", order_by="TeamMember.joined_at", cascade="all, delete-orphan"
    )


class TeamMember(Base):
    __tablename__ = "quiz_team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_quiz_team_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("quiz_teams.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("quiz_users.id"), index=True)
    score: Mapped[float] = mapped_column(Float, default=0)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    team: Mapped[Team] = relationship(back_populates="members")
    user: Mapped[User] = relationship()
    answers: Mapped[list["TeamAnswer"]] = relationship(back_populates="member", cascade="all, delete-orphan")


class TeamAnswer(Base):
    __tablename__ = "quiz_team_answers"
    __table_args__ = (UniqueConstraint("member_id", "question_id", name="uq_quiz_team_answer_once"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("quiz_team_members.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("quiz_questions.id"))
    given: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    member: Mapped[TeamMember] = relationship(back_populates="answers")


class PsychResult(Base):
    """心理測驗結果（登入使用者才保存），code 用於分享連結與默契配對。"""

    __tablename__ = "quiz_psych_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("quiz_users.id"), index=True, nullable=True)
    slug: Mapped[str] = mapped_column(String(20))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User | None] = relationship()


class PsychIllust(Base):
    """心理測驗插畫（例如 shigureni free illust）。存在資料庫，不放進公開的 git repo。"""

    __tablename__ = "quiz_psych_illusts"

    slug: Mapped[str] = mapped_column(String(20), primary_key=True)
    mime: Mapped[str] = mapped_column(String(20))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
