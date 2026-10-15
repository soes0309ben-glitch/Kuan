import hashlib
import logging
import secrets
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LINE 記帳本"
    secret_key: str = ""
    database_url: str = "sqlite:///./expense.db"
    base_url: str = "http://127.0.0.1:8000"
    # 「今天」「本月」都以這個時區計算
    timezone: str = "Asia/Taipei"

    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    line_bot_add_friend_url: str = ""

    line_login_channel_id: str = ""
    line_login_channel_secret: str = ""

    cron_token: str = ""
    dev_login: bool = False

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def line_login_enabled(self) -> bool:
        return bool(self.line_login_channel_id and self.line_login_channel_secret)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.secret_key.strip():
        # 隨機密鑰每次重啟都會變（所有人被登出、魔法連結失效），所以優先由其他機密推導出固定值
        material = "|".join(
            v for v in (settings.line_channel_secret, settings.line_login_channel_secret) if v
        )
        if material:
            settings.secret_key = hashlib.sha256(f"expense-app-session|{material}".encode()).hexdigest()
            logger.warning("SECRET_KEY 未設定，已由 LINE channel secret 推導出固定值。建議另外設定 SECRET_KEY。")
        else:
            settings.secret_key = secrets.token_hex(32)
            logger.warning("SECRET_KEY 未設定，已暫時隨機產生（重啟後需重新登入）。正式上線前請設定 SECRET_KEY。")
    return settings
