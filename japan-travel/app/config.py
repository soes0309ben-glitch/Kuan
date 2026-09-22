import logging
import secrets
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_INSECURE_DEFAULT_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "旅日誌｜日本旅遊行程規劃"
    secret_key: str = _INSECURE_DEFAULT_SECRET
    database_url: str = "sqlite:///./japan_travel.db"

    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""

    unsplash_access_key: str = ""
    newsapi_key: str = ""

    resend_api_key: str = ""
    notify_email: str = ""
    notify_from_email: str = ""

    admin_emails: str = ""

    base_url: str = "http://127.0.0.1:8000"

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.secret_key or settings.secret_key == _INSECURE_DEFAULT_SECRET:
        # Never sign session cookies with the publicly-known default value.
        # Generated fresh per process (not persisted), so this only costs
        # existing sessions on restart — acceptable for a dev default, and
        # forces anyone deploying for real to set SECRET_KEY explicitly.
        settings.secret_key = secrets.token_hex(32)
        logger.warning(
            "SECRET_KEY not set in .env — generated a random one for this process. "
            "Sessions will not survive a restart. Set SECRET_KEY in .env before deploying."
        )
    return settings
