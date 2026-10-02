import re

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# Normalize whatever Postgres URL scheme shows up (Render's legacy
# "postgres://", a manually-added "postgresql+psycopg://", etc.) to plain
# "postgresql://" so SQLAlchemy always loads the psycopg2 dialect — the
# only Postgres driver actually in this project's dependencies. Without
# this, a mismatched scheme crashes the app at startup with either
# NoSuchModuleError (unrecognized scheme) or ModuleNotFoundError (a driver
# that was never installed, like psycopg v3).
database_url = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql://", settings.database_url)

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
