import re

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

# Render 給的可能是舊式 postgres:// 網址；一律明確指定 psycopg2 驅動。
# SQLAlchemy 2.1 起 postgresql:// 預設改用 psycopg（第 3 版），但本專案安裝的是 psycopg2。
database_url = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql+psycopg2://", get_settings().database_url.strip())

if not database_url.startswith(("postgresql+psycopg2://", "sqlite:///")):
    # 只印出開頭，避免把網址裡的資料庫密碼寫進 log
    scheme = database_url.split("://", 1)[0] if "://" in database_url else database_url[:12]
    raise RuntimeError(
        f"DATABASE_URL 格式不正確（目前以「{scheme}」開頭）。"
        "請改成 Render PostgreSQL 的 Internal 或 External Database URL，應以 postgresql:// 或 postgres:// 開頭；"
        "網站網址請填在 BASE_URL。"
    )

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401 註冊所有資料表

    Base.metadata.create_all(bind=engine)
