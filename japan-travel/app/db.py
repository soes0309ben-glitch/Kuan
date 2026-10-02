import re

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# Normalize whatever Postgres URL scheme shows up (Render's legacy
# "postgres://", a manually-added "postgresql+psycopg://", etc.) to an
# explicit "postgresql+psycopg2://" — psycopg2 is the only Postgres driver
# in this project's dependencies. The driver must be named: SQLAlchemy 2.1
# made psycopg v3 the default for plain "postgresql://", so leaving it off
# crashes startup with ModuleNotFoundError: No module named 'psycopg'.
database_url = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql+psycopg2://", settings.database_url)

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args)
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
    from app import models  # noqa: F401 ensures models are registered

    Base.metadata.create_all(bind=engine)
