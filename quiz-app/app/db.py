import re

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

# Render 給的可能是舊式 postgres:// 網址，統一成 SQLAlchemy 認得的 postgresql://
database_url = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql://", get_settings().database_url)

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
