import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    purchases: Mapped[list["Purchase"]] = relationship(back_populates="user")


class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    itinerary_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_twd: Mapped[int] = mapped_column(Integer, nullable=False)
    stripe_session_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    user: Mapped["User"] = relationship(back_populates="purchases")


class PageView(Base):
    __tablename__ = "page_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    session_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, index=True
    )


class ContentOverride(Base):
    """Admin-authored add/edit/delete on top of the shipped attractions.json
    / itineraries.json seed data, so edits persist in the database (and
    survive redeploys) instead of being written back to files on disk.
    """

    __tablename__ = "content_overrides"
    __table_args__ = (UniqueConstraint("kind", "item_id", name="uq_content_override_kind_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    item_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )
